# Session replay rasterizer

Temporal worker that converts session replays into MP4 videos using Puppeteer + Chromium.
Runs on a dedicated `rasterization-task-queue`.

## Architecture

```text
Temporal workflow (Python)
  └─ dispatches activity to rasterization-task-queue
       └─ Node.js worker picks it up
            ├─ rasterizeRecording (Puppeteer records the replay to raw MP4)
            ├─ postProcessToMp4 (ffmpeg: strip pre-roll, trim, speed correct)
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
| `recorder.ts`     | Puppeteer recording logic (puppeteer-screen-recorder)            |
| `postprocess.ts`  | ffmpeg post-processing (trim, speed correction, fps)             |
| `browser-pool.ts` | Warm Chromium lifecycle manager                                  |
| `storage.ts`      | S3 upload                                                        |
| `config.ts`       | Environment variable configuration                               |
| `types.ts`        | Input/output contracts                                           |

## Two pipelines

- **User video exports**: full pipeline with ffmpeg post-processing (strip pre-roll, trim to duration, apply speed correction)
- **AI/Gemini pipeline**: `skip_postprocessing: true` — uploads raw recording directly

## Running locally

```bash
bin/temporal-recording-rasterizer-worker
```

Requires Chromium and ffmpeg installed locally.

## Docker

```bash
docker build -f Dockerfile.recording-rasterizer -t posthog-recording-rasterizer .
```

Uses Debian `chromium` package (not Puppeteer's bundled download).
