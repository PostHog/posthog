# Session replay rasterizer

Temporal worker that converts session replays into MP4 videos using puppeteer-capture's
`HeadlessExperimental.beginFrame` for deterministic virtual-time frame capture.
Runs on a dedicated `rasterization-task-queue`.

## Architecture

```text
Temporal workflow (Python)
  └─ dispatches activity to rasterization-task-queue
       └─ Node.js worker picks it up
            ├─ rasterizeRecording (puppeteer-capture: deterministic frame capture)
            ├─ postProcessVideo (ffmpeg: slow to real-time speed, optional trim)
            ├─ computeVideoTimestamps (map session time → video time)
            ├─ uploadToS3
            └─ return metadata
```

The worker maintains a warm Chromium browser pool —
a single browser instance is reused across exports and recycled after N uses.

## Modules

| File              | Purpose                                                          |
| ----------------- | ---------------------------------------------------------------- |
| `index.ts`        | Worker entry point — launches browser pool, connects to Temporal |
| `activities.ts`   | Temporal activity: record → postprocess → upload → cleanup       |
| `recorder.ts`     | puppeteer-capture deterministic recording with virtual time      |
| `postprocess.ts`  | ffmpeg post-processing (speed correction, trim) + video timestamps |
| `browser-pool.ts` | Warm Chromium lifecycle manager                                  |
| `storage.ts`      | S3 upload                                                        |
| `config.ts`       | Environment variable configuration                               |
| `types.ts`        | Input/output contracts                                           |

## Running locally

The rasterizer runs in Docker since `beginFrame` requires Linux chrome-headless-shell:

```bash
bin/temporal-recording-rasterizer-worker
```

This builds TypeScript locally, builds the Docker image (with hash-based caching),
and starts the container with volume mounts for fast iteration.
