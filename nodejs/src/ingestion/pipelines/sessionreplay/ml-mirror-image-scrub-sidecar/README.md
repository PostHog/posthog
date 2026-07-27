# Replay Vision ML Mirror Image Scrub Sidecar

This package builds a small sidecar that is installed alongside the image scrubber kafka consumer at `nodejs/src/servers/ingestion-session-replay-ml-image-scrub-server.ts`

It is intentionally kept separate from the root pnpm workspace, as the ML deps are several hundred MB. I did not want to add this to every CI run, every dev's local machine's worktree, etc

It runs a simple http server, receives an image and replies with the scrubbed image. The `/scrub` interface is fully trusted as it only communicates with the kafka consumer in the same pod. It binds loopback only, so it must run as a sidecar container sharing the consumer's network namespace, not as its own service.

`/metrics` and the health probes are served on a separate listener bound to all interfaces (default port `9011`, `IMAGE_SCRUB_METRICS_PORT`) so Prometheus and the kubelet can reach them on the pod IP. That listener exposes no image bytes, only counters and probes.

## HTTP contract

`POST /scrub` with the raw image bytes returns the scrubbed bytes (200). The status split is load-bearing and both sides must change together: the consumer permanently skips 413 (too large) and 422 (undecodable), and retries then **drops** the image on 500 (transient) and 503 (busy). See `scrub-client.ts` for the consumer half.

A dropped image is counted in `ml_mirror_image_scrub_consumer_dropped_total` (by `reason`: `busy`, `timeout`, `transport`, `aborted`, `deadline`, `unattempted`) and never reaches the bucket, so the failure costs coverage rather than leaking content.
That counter is the lane's only health signal, so `IngestionSessionReplayImageScrubDropRate` alerts on its ratio to `..._scrubbed_total`: a pod dropping every image still passes its probes, keeps its lag flat, and keeps advancing offsets.
Note `unattempted`: when a batch exhausts `SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BATCH_SCRUB_MS` the rest of that poll batch is dropped without being offered to the sidecar at all, because Kafka offsets are a high-water mark and a later batch would commit past them regardless.

**Nothing about a busy or unreachable sidecar may take the consumer down.**
The consumer's Kafka loop exits the process on any batch error, so a failure that reaches it costs the whole pod and hands its partitions to pods that are equally busy, spreading the saturation.
A consumer restart cannot fix the sidecar in any case: it is a separate container that keeps running.

`maxConcurrency` is derived from `SCRUB_WORKERS` rather than set independently, so the sidecar sheds load it cannot execute instead of admitting it into an accept queue.
That matters because the consumer's per-request timeout is an inactivity timeout: a queued request sends no bytes, so queueing reads to the consumer as an unresponsive sidecar rather than a busy one, and a fast 503 is the signal it can actually act on.

## The scrub

Given an image, `advancedScrub` (`src/scrub.ts`):

1. **Plan the sizes**: `planScales` (`src/scale-plan.ts`) decides every resize from the source dimensions alone, before a pixel is read — the decoded frame, what each detector sees, and what gets stored.
   An area budget rather than a long-side cap, so tall pages keep legible native resolution instead of being squashed.
   Faces are detected on a letterboxed (never squashed) 640×640 input; frames beyond 3:1 aspect are tiled along their long axis (overlapping windows) so a face on a tall page stays above the detector's minimum size instead of shrinking past it.
2. **NSFW/gore gate**: if the image is explicit or gory (NSFL + NSFW probability over `NSFW_THRESHOLD`), it collapses to a 1x1 blank.
3. **Face redaction**: every detected face (YuNet) is filled with its **mean colour**.
4. **Text redaction**: every detected text region (DBNet) gets the same fill, with a margin scaled to the box height (= font size).
   We detect _where_ text is and never read it.
5. **Code redaction**: every decodable QR/barcode (zxing) gets the same fill — a TOTP provisioning QR or ticket barcode is machine-readable PII that the face/text detectors can't see.

The goal is to protect data labellers and reduce PII exposure.
It does not need to be perfect; the self-verifying test (below) keeps it honest.

**Why solid fill, not blur/mosaic.** Blur and pixelation are low-pass filters: they remove fine detail but keep coarse structure, so large text (titles, headings) stays legible to a capable reader — we confirmed an LLM could still read blurred titles and the opening sentence of a test page — and a mosaicked face can be re-smoothed back into something a detector finds again.
A solid, quantized mean-colour fill removes the information entirely, so faces, text, and codes all get it.
The fill's edges are feathered by blurring the fill's _colour_ only, never the mask, so nothing under a box is ever revealed.

## This is native code, not ML-in-JS

All model inference and image processing run in optimized native libraries.
The TypeScript is orchestration plus lightweight output decoding (over small downscaled maps, not full images):

| Stage                              | Library            | Native engine        |
| ---------------------------------- | ------------------ | -------------------- |
| NSFW/gore classify (SwiftFormer)   | `onnxruntime-node` | ONNX Runtime (C++)   |
| Face detection (YuNet)             | `onnxruntime-node` | ONNX Runtime (C++)   |
| Text detection (DBNet / PP-OCRv3)  | `onnxruntime-node` | ONNX Runtime (C++)   |
| QR/barcode detection               | `zxing-wasm`       | zxing-cpp (C++/wasm) |
| resize / blur / composite / encode | `sharp`            | libvips (C++)        |

We do not train anything and run no neural nets in JS.
The only hand-written JS is model-output decoding (DBNet threshold + dilation + connected components, YuNet anchor decode + NMS, tensor packing, mask fill), which runs over the small detection maps and is not the bottleneck.
Everything model-shaped runs on ONE runtime (onnxruntime-node) on purpose: a second ML runtime would mean a second native-binary compatibility surface and a second set of failure modes (Node-version coupling, slow fallback backends).

## Layout

`src/` is production (ships in the sidecar image; tests co-locate as `*.test.ts` and are stripped from the image); `dev/` is everything non-production (benchmarks, the eval harness, data setup).
Production never imports from `dev/`.

```text
src/  (production — ships)
  main.ts         entrypoint: start the worker pool -> start servers
  pool.ts         the inference workers: dispatch, per-job deadlines, replace the dead
  scrub-worker.ts one worker thread: owns its ONNX sessions, scrubs one image at a time
  worker-protocol.ts  the job/reply messages crossing the thread boundary
  cores.ts        worker + ORT thread sizing from the cgroup CPU quota and memory limit
  server.ts       the /scrub + /metrics listeners; scrub implementation injected
  config.ts       env-driven runtime config
  blur.ts         baseline blur (kept in sync with rust/replay-anonymizer/src/blur.rs)
  scrub.ts        the ML scrub pipeline: decode-once, NSFW gate, solid-fill of faces/text/codes
  yunet.ts        YuNet face detector (ONNX)
  dbnet.ts        DBNet text-region detector (ONNX)
  qr.ts           QR/barcode detector (zxing-wasm, loaded from node_modules — no egress)
  scale-plan.ts   every resize decided in one pure function, before a pixel is read
  floors.ts       what each detector finds vs what a person can read, and where both were measured
  src-image.ts    decode the source once to raw RGB, to the size the plan asked for
  geometry.ts     shared Box type + grid rounding
  safety.ts       NSFW/gore gate (SwiftFormer image-safety classifier, ONNX)
  smoke.ts        image-build-time smoke test: models load + one scrub, with networking disabled
  env.ts          validated numeric env knobs — invalid values refuse to start (never fail open)
  metrics.ts      Prometheus registry: HTTP outcomes + scrub outcome signals

dev/  (non-production)
  scrub-eval.ts   OCR + face-redaction eval over downloaded images (npm run eval)
  verify.ts       quick OCR-readability check
  bench.ts scale.ts worker-proc.ts   latency + throughput benchmarks
  make-corpus.ts  synthetic screenshot corpus
  setup.ts        download ONNX models + sample test images (npm run setup)

fixtures/  committed eval fixtures (e.g. a retina Wikipedia page: dense text + a face)
models/  test-data/  corpus/  out/   downloaded/generated by setup (gitignored)
```

## Run

```bash
pnpm install --ignore-workspace   # standalone package: own lockfile, outside the root workspace
npm run setup        # download ONNX models + sample test images, generate the corpus
npm run test:unit    # fast unit tests (no models/network)
npm run eval         # scrub-quality suite (text + face) over real images
npm run bench        # latency + per-stage breakdown
npm run smoke        # models load + one scrub end to end (what the image build runs)
npm run start        # the sidecar server (needs `npm run setup` for the models)
```

If the model/data downloads fail with a TLS chain error, your machine is missing an intermediate CA.
Point `NODE_EXTRA_CA_CERTS` at a complete bundle (e.g. certifi's `cacert.pem`) rather than disabling certificate validation.

## The self-verifying test

The production path _detects_ text with DBNet (fast).
The test _reads_ the scrubbed output with OCR (tesseract, a different model doing recognition not detection) and counts confident multi-character words.
OCR generally reads degraded text better than people, so "OCR can't read it" is a conservative proxy for "a labeller can't".
The face check re-runs YuNet at high sensitivity on the scrubbed output and asserts no face still sits (by IoU) where one was; a successfully solid-filled face is no longer detectable.

The suite **gates** on session replay's representative domain (crisp rendered-UI text + faces) and **reports** on a harder scanned-document set:

```text
UI TEXT (gated):        31/31 clean, 0.0% leak   [PASS]   # rendered screenshots
DOCUMENT TEXT (report): 19/20 clean, 2.7% worst  [report] # faint fax/scan print, out of domain
FACE:                   89/89 faces redacted (100%)
```

The corpus spans 0.3 to 8.3 megapixels at both device pixel ratios, which matters: it used to top out
at 1440x900, entirely under the frame budget, so nothing in it was ever downscaled on the
way to detection and the suite could not see what that cap costs. Adding monitor-sized frames
immediately failed the gate at a 14.3% leak on 4K captures taken at device pixel ratio 1, where 14px
text reaches DBNet at about 6px after both downscales. `DET_SHARPEN` closes that, and the numbers
above are with it on.

Faint, low-contrast scanned-fax lines occasionally survive.
That is contrast-limited not size-limited, so resolution alone won't catch every faded line, and it is outside the rendered-UI domain and within the "best-effort, not catastrophic if a little gets through" bar.
Raising `SCRUB_SAFETY_FACTOR` spends more CPU on recall: it enlarges the frame every detector sees, since the frame budget is derived from it.

## Resolution

One rule sets every size: **each detector must see a subject at least `ratio` times larger, per axis, than the stored image keeps it.**
Anything still readable in the artifact was therefore large enough to have been found and filled.

`ratio` is derived rather than chosen, from measured floors in `src/floors.ts` — what each detector reliably finds, against what a person can still read out of the stored image.
Faces bind at 64/21 ≈ 3.05; text is 7/3 ≈ 2.33; codes constrain nothing, since a code degraded past decoding carries nothing.
`SCRUB_SAFETY_FACTOR` (default 1.3) is margin on top, because both floors came from one font at near-black on white and low-contrast text moves the detection floor the wrong way.

**`SCRUB_OUT_MAX_PIXELS` (default 50,000) is the only knob most people should touch.**
It is what gets stored, and everything else follows from it: the frame budget is `stored x ratio^2`, because the detectors have to see enough to keep the rule.
Setting the frame budget independently is what let two individually-reasonable settings combine into a pipeline that under-redacted, so `SCRUB_MAX_PIXELS` still exists as an override but is derived by default.

Storing small is deliberate and is most of the guarantee. The downstream consumer identifies what kind of site a session is on, so it needs scene structure and not legibility — text being unreadable in the artifact is the point, not a cost.
At the defaults a 1080p capture is stored at about 161x90.

Re-derive the floors with `tsx dev/glyph-floor.ts` (text) and `tsx dev/floors.ts` (faces and codes); both read their geometry from `limitsFromEnv()` so they cannot drift from what ships.

## Models are baked into the image

The three ONNX models (safety gate, YuNet, DBNet) are `ADD`ed in `Dockerfile.ml-mirror-image-scrub` (repo root) from commit-pinned upstream URLs with BuildKit `--checksum` verification (same pins + sha256 checks as `dev/setup.ts` — keep them in sync).
zxing's wasm loads from `node_modules`.
A build-time smoke test (`src/smoke.ts`) then loads the models and runs one scrub with networking disabled, so a broken model, a native-binary mismatch, or an accidental runtime network dependency fails the image build instead of crash-looping the deploy.
The sidecar makes no network fetches at startup.

## Observability

Beyond the HTTP outcome counters (scrubbed/failed/undecodable/rejected/too-large/aborted, duration, output bytes), `/metrics` carries the outcome signals a privacy control needs:

- `..._blanked_total` — NSFW-gate blanks are destructive and irreversible; alert on rate spikes.
- `..._faces_redacted_total`, `..._text_boxes_redacted_total`, `..._codes_redacted_total` — a sustained zero rate under traffic means a detector outage (un-redacted output), not a clean stream.
