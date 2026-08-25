# Replay Vision ML Mirror Image Scrub Sidecar

This package builds a small sidecar that is installed alongside the image scrubber kafka consumer at `nodejs/src/servers/ingestion-session-replay-ml-image-scrub-server.ts`

It is intentionally kept separate from the root pnpm workspace, as the ML deps are several hundred MB. I did not want to add this to every CI run, every dev's local machine's worktree, etc

It runs a simple http server, receives an image and replies with the scrubbed image. The `/scrub` interface is fully trusted as it only communicates with the kafka consumer in the same pod. It binds loopback only, so it must run as a sidecar container sharing the consumer's network namespace, not as its own service.

`/metrics` and the health probes are served on a separate listener bound to all interfaces (default port `9011`, `IMAGE_SCRUB_METRICS_PORT`) so Prometheus and the kubelet can reach them on the pod IP. That listener exposes no image bytes, only counters and probes.

## HTTP contract

`POST /scrub` with the raw image bytes returns the scrubbed bytes (200). The status split is load-bearing and both sides must change together: the consumer permanently skips 413 (too large) and 422 (undecodable), and **waits and retries** on 500 (transient) and 503 (busy). See `scrub-client.ts` for the consumer half.

**A busy sidecar is waited on, never given up on, and no image is ever dropped for lack of capacity.**
Kafka is already holding the image durably, so a bounded retry buys nothing except the chance to discard data the log was keeping safe, while consuming more slowly costs only lag, which is what the topic is for.
There is no batch time limit and no drop path: every message a poll batch takes is finished before any offset moves past it.

The waiting _is_ the backpressure. A batch that spends longer on a jammed sidecar calls `consume()` that much later, so the consumer paces itself to whatever the sidecar can execute without needing to pause partitions explicitly.
Lag grows while that happens, which is correct and is what the drain-time panels on the dashboard are for.

Because the batch has no time limit, its duration is set by how many images it holds, so this lane runs a small `CONSUMER_BATCH_SIZE` (50, against a default of 500).
A batch that outlives `max.poll.interval.ms` (300s) gets the pod evicted mid-batch, and that is not a clean retry: the evicted pod loses the offsets for work it already did, and the partition lands on a pod whose sidecar is equally busy and redoes the same images, so offered load rises while throughput falls.
Keeping batches far inside the interval is what stops ordinary saturation reaching that point.
If a revoke does land mid-batch, the batch stops as soon as a flush finds it no longer owns the partitions, rather than scrubbing on and writing a second shard for a span the new owner is already writing.

A wedged sidecar still blocks its partitions rather than draining them, and no batch size prevents that.

## Images the sidecar cannot process

An image that fails the same way forever would otherwise hold the head of its partition against every team whose records share it, and the bytes are user-controlled, so that is a stall anyone can cause.
Such an image is parked on `session_replay_image_scrub_dlq` and the partition moves on.

The bytes published there are the **originals, never scrubbed**, so that topic holds unredacted content and nothing may treat it as scrubbed.
Keeping them is the point: discarding would destroy the only reproduction of the sidecar bug that rejected them, and 30 days of retention is the window to fix the sidecar and replay.
It is the same content the source topic already carries, on the same cluster, and it expires the same way: neither topic sets `cleanup.policy`, so both take Kafka's `delete` default and segments age out on their own.
The one difference is that a parked image outlives its source copy, 30 days against 7, which is deliberately the width of that window.
Why it was parked travels in headers, so the topic can be triaged without reading image content.

**What makes an image poison rather than unlucky is the only question that matters here.**
Under saturation every image waits a long time, so anything keyed on waiting or failure count alone would park the entire stream during a backlog, which is the mass loss the wait exists to prevent arriving through a different door.
An image is blamed only when it keeps failing **while other images succeed**: a sidecar that is full or wedged fails everything equally, so no image ever meets that condition and the lane keeps waiting, which is correct.
Only a considered answer counts towards blame, which is the `rejected` reason: the sidecar took the image, looked at it, and could not produce bytes.
A 503 is it declining to look at all, and a refused or reset socket is true of every image at once.

**The two deadlines are ordered on purpose, and inverting them reopens a hole.** The sidecar gives up on a job it cannot finish first (`IMAGE_SCRUB_JOB_TIMEOUT_MS`), retires the worker, and answers 500, which is a considered answer about that image and is what lets it be blamed and parked.
The consumer waits longer than that (`SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS`, past the job deadline plus admission queue wait) so the answer actually arrives.
Give up first and an unprocessable image looks merely slow on every attempt, never earns blame, and holds the head of a partition shared by every team whose records hash to it.
A timeout then means what it should: the sidecar said nothing at all, which is true of every image at once and so is not blamable.

The number of other successes required is deliberately small, and must stay below the pod's scrub concurrency.
A batch cannot finish while one of its images is in flight, and a pod cannot poll for more work until its batch finishes, so the only successes that can ever arrive are from the few slots running alongside that image.
Requiring more than that makes the gate unreachable for an image late in a batch: the batch never returns, and the pod stops consuming entirely while still reporting Ready.
`ImageBatcher` refuses to start if the relationship is broken, so a future concurrency change fails at boot rather than in traffic.

When no peer is available to vouch at all, a long enough run of considered rejections opens the gate on its own.
That threshold has to fire comfortably inside `max.poll.interval.ms` (300s), which is the binding constraint rather than a preference: a batch cannot return while one of its images is in flight, so anything above the lease can never be reached — the group fences the pod first, the partition moves, and its new owner repeats the same work and is fenced in turn, circling the fleet forever.

It is published through this lane's own producer slot on the replay cluster, which is where the source topic lives and which carries a `message.max.bytes` sized for these payloads; the generic slot points elsewhere with librdkafka's 1 MB default, where parking a normal image would fail on every attempt.
The topic must exist before this ships, with `max.message.bytes` at least the source topic's: clearing `SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC` is the rollback, and reverts to waiting.

Parking happens before the ref is marked and before the slot retires, so a failed publish leaves the image exactly where it was, still unscrubbed and still uncommitted.
A publish that keeps failing is retried rather than raised, because the Kafka loop exits the process on any batch error and a dead-letter topic that is missing, on the wrong cluster, or too small would otherwise crash-loop every pod in the lane on the same image.
`ml_mirror_image_scrub_consumer_dead_letter_failed_total` is that condition, and it means the topic needs looking at rather than the image.
With no dead-letter destination configured the client keeps waiting instead, because the only other option would be discarding.
`ml_mirror_image_scrub_consumer_dead_lettered_total` should sit at zero; anything above a trickle is a sidecar bug reproducing across many images, and the fix belongs in the sidecar.

Waiting only applies to answers a later attempt could change: 5xx, 408, 429, and transport failures (a refused socket is the ordinary case while the sidecar is still starting in the same pod).
Any other status, and a 200 carrying no bytes, is the sidecar answering a question we did not think we were asking, so it fails the batch loudly instead.
Waiting on a 404 from a misdirected `SIDECAR_URL` would otherwise turn a deploy mistake into a pod that consumes nothing, passes every probe, and surfaces only as lag.

`ml_mirror_image_scrub_consumer_scrub_waits_total` (by `reason`: `busy`, `timeout`, `transport`) counts attempts that came back without bytes and will be retried, so it is a saturation signal and never a loss signal.
`ml_mirror_image_scrub_consumer_stuck_images_total` re-increments while any one image is still being retried past the point a healthy sidecar would have finished it, so it reads as a level rather than a one-off edge.

**A stalled pod on this lane looks healthy to Kubernetes.** The lane runs the legacy heartbeat health check (`CONSUMER_LOOP_BASED_HEALTH_CHECK` is unset), and the consumer refreshes that heartbeat every 10s for the whole batch, so a pod blocked on one image stays Ready and Live indefinitely.
That is deliberate — restarting it would only replay the same image — but it means lag and the two counters above are the only evidence, and it is why the lane's alerts are lag-shaped.

**Nothing about a busy or unreachable sidecar may take the consumer down.**
The consumer's Kafka loop exits the process on any batch error, so a failure that reaches it costs the whole pod and hands its partitions to pods that are equally busy, spreading the saturation.
A consumer restart cannot fix the sidecar in any case: it is a separate container that keeps running.

`maxConcurrency` is derived from `SCRUB_WORKERS` rather than set independently, so the sidecar sheds load it cannot execute instead of admitting it into an accept queue.
That matters because the consumer's per-request timeout is an inactivity timeout: a queued request sends no bytes, so queueing reads to the consumer as an unresponsive sidecar rather than a busy one, and a fast 503 is the signal it can actually act on.

## The scrub

Given an image, `advancedScrub` (`src/scrub.ts`):

1. **Apply the image policy**: reject an image when its XMP `plus:DataMining` value prohibits AI training.
2. **Plan the sizes**: `planScales` (`src/scale-plan.ts`) decides every resize from the source dimensions alone, before a pixel is read — the decoded frame, what each detector sees, and what gets stored.
   An area budget rather than a long-side cap, so tall pages keep legible native resolution instead of being squashed.
   Faces are detected on a letterboxed (never squashed) 640×640 input; frames beyond 3:1 aspect are tiled along their long axis (overlapping windows) so a face on a tall page stays above the detector's minimum size instead of shrinking past it.
3. **NSFW/gore gate**: if the image is explicit or gory (NSFL + NSFW probability over `NSFW_THRESHOLD`), it collapses to a 1x1 blank.
4. **Face redaction**: every detected face (YuNet) is filled with its **mean colour**.
5. **Text redaction**: every detected text region (DBNet) gets the same fill, with a margin scaled to the box height (= font size).
   We detect _where_ text is and never read it.
6. **Code redaction**: every decodable QR/barcode (zxing) gets the same fill — a TOTP provisioning QR or ticket barcode is machine-readable PII that the face/text detectors can't see.

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
  image-input.ts  accepted image decoders, pixel limits, and embedded metadata policy
  xmp.ts          PLUS Data Mining metadata parser

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
