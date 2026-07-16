# Replay Vision ML Mirror Image Scrub Sidecar

This package builds a small sidecar that is installed alongside the image scrubber kafka consumer at `nodejs/src/servers/ingestion-session-replay-ml-image-scrub-server.ts`

It is intentionally kept separate from the root pnpm workspace, as the ML deps are several hundred MB. I did not want to add this to every CI run, every dev's local machine's worktree, etc

It runs a simple http server, receives an image and replies with the scrubbed image. The `/scrub` interface is fully trusted as it only communicates with the kafka consumer in the same pod. It binds loopback only, so it must run as a sidecar container sharing the consumer's network namespace, not as its own service.

`/metrics` and the health probes are served on a separate listener bound to all interfaces (default port `9011`, `IMAGE_SCRUB_METRICS_PORT`) so Prometheus and the kubelet can reach them on the pod IP. That listener exposes no image bytes, only counters and probes.

## HTTP contract

`POST /scrub` with the raw image bytes returns the scrubbed bytes (200). The status split is load-bearing and both sides must change together: the consumer permanently skips 413 (too large) and 422 (undecodable), and retries then replays 500 (transient) and 503 (busy). See `scrub-client.ts` for the consumer half.

## The scrub

Given an image, `advancedScrub` (`src/scrub.ts`):

1. **Downscale**: every frame is capped at the `SCRUB_MAX_PIXELS` area budget (default 1600², aspect preserved) inside the decode.
   This bounds the per-image memory working set, and — since text detection runs under the same area budget — the stored output never carries resolution the detectors didn't certify as clean.
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
  main.ts         entrypoint: load models -> start servers
  server.ts       the /scrub + /metrics listeners; scrub implementation injected
  config.ts       env-driven runtime config
  blur.ts         baseline blur (kept in sync with rust/replay-anonymizer-node/src/blur.rs)
  scrub.ts        the ML scrub pipeline: decode-once, NSFW gate, solid-fill of faces/text/codes
  yunet.ts        YuNet face detector (ONNX)
  dbnet.ts        DBNet text-region detector (ONNX)
  qr.ts           QR/barcode detector (zxing-wasm, loaded from node_modules — no egress)
  src-image.ts    decode the source once to raw RGB (area-capped), shared across stages
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
UI TEXT (gated):        12/12 clean, 0.0% leak   [PASS]   # rendered screenshots
DOCUMENT TEXT (report): 18/20 clean, 5.2% worst  [report] # faint fax/scan print, out of domain
FACE:                   88/88 faces redacted (100%)
```

Faint, low-contrast scanned-fax lines occasionally survive.
That is contrast-limited not size-limited, so resolution alone won't catch every faded line, and it is outside the rendered-UI domain and within the "best-effort, not catastrophic if a little gets through" bar.
Raise `DET_FACTOR` (env, default 0.75 of the long side) toward 1.0 to spend more CPU on text recall.

## Models are baked into the image

The three ONNX models (safety gate, YuNet, DBNet) are `ADD`ed in `Dockerfile.ml-mirror-image-scrub` (repo root) from commit-pinned upstream URLs with BuildKit `--checksum` verification (same pins + sha256 checks as `dev/setup.ts` — keep them in sync).
zxing's wasm loads from `node_modules`.
A build-time smoke test (`src/smoke.ts`) then loads the models and runs one scrub with networking disabled, so a broken model, a native-binary mismatch, or an accidental runtime network dependency fails the image build instead of crash-looping the deploy.
The sidecar makes no network fetches at startup.

## Observability

Beyond the HTTP outcome counters (scrubbed/failed/undecodable/rejected/too-large/aborted, duration, output bytes), `/metrics` carries the outcome signals a privacy control needs:

- `..._blanked_total` — NSFW-gate blanks are destructive and irreversible; alert on rate spikes.
- `..._faces_redacted_total`, `..._text_boxes_redacted_total`, `..._codes_redacted_total` — a sustained zero rate under traffic means a detector outage (un-redacted output), not a clean stream.
