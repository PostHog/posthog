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
            ├─ computeVideoTimestamps (map session time → video time)
            ├─ uploadToS3
            └─ return metadata
```

The worker maintains a warm Chromium browser pool —
a single browser instance is reused across exports and recycled after N uses.

Screenshots default to JPEG (q=80) via a CDP session monkey-patch,
giving ~30% faster frame capture than the hardcoded PNG in puppeteer-capture.

## Directory structure

```text
recording-rasterizer/
├── index.ts              ← thin entry point, delegates to temporal/worker.ts
├── config.ts             ← environment variable configuration
├── errors.ts             ← RasterizationError class
├── logger.ts             ← pino logger factory
├── metrics.ts            ← Prometheus metrics
├── types.ts              ← input/output contracts
├── utils.ts              ← timing utilities
├── storage.ts            ← S3 upload
├── postprocess.ts        ← map inactivity periods to video timestamps
│
├── temporal/             ← Temporal integration
│   ├── worker.ts         ← worker bootstrap (browser pool, Temporal connection, metrics server)
│   ├── activities.ts     ← activity handler (record → upload → cleanup)
│   └── codec.ts          ← Fernet encryption codec for Temporal payloads
│
├── capture/              ← Puppeteer capture pipeline
│   ├── browser-pool.ts   ← warm Chromium lifecycle manager
│   ├── recorder.ts       ← orchestrates page setup → player load → capture
│   ├── player.ts         ← PlayerController + config builder for rrweb player
│   └── capture.ts        ← frame capture loop, screenshot format override
│
└── __tests__/            ← all tests
```

## Running locally

The rasterizer runs in Docker since `beginFrame` requires Linux chrome-headless-shell:

```bash
bin/temporal-recording-rasterizer-worker
```

This builds TypeScript locally, builds the Docker image (with hash-based caching),
and starts the container with volume mounts for fast iteration.

## Configuration

Key environment variables (see `config.ts` for full list):

| Variable                    | Default | Description                                           |
| --------------------------- | ------- | ----------------------------------------------------- |
| `SCREENSHOT_FORMAT`         | `jpeg`  | Screenshot format for frame capture (`jpeg` or `png`) |
| `SCREENSHOT_JPEG_QUALITY`   | `80`    | JPEG quality (1-100), only used when format is `jpeg` |
| `MAX_CONCURRENT_ACTIVITIES` | `4`     | Max parallel recording activities                     |
| `BROWSER_RECYCLE_AFTER`     | `100`   | Recycle Chromium after N page uses                    |
| `CAPTURE_BROWSER_LOGS`      | `0`     | Forward browser console/error logs to worker logger   |

## Activity inputs

The `rasterize-recording` activity accepts `RasterizeRecordingInput` (see `types.ts`):

| Field                  | Required | Default | Description                                    |
| ---------------------- | -------- | ------- | ---------------------------------------------- |
| `session_id`           | yes      | —       | Session to rasterize                           |
| `team_id`              | yes      | —       | Team ID                                        |
| `s3_bucket`            | yes      | —       | S3 bucket for output                           |
| `s3_key_prefix`        | yes      | —       | S3 key prefix                                  |
| `playback_speed`       | no       | `4`     | Playback speed multiplier                      |
| `recording_fps`        | no       | `24`    | Output video framerate                         |
| `start_timestamp`      | no       | —       | Start playback from this time (ms since epoch) |
| `end_timestamp`        | no       | —       | Stop playback at this time (ms since epoch)    |
| `trim`                 | no       | —       | Max output duration in seconds                 |
| `capture_timeout`      | no       | —       | Max capture time in seconds                    |
| `viewport_width`       | no       | `1280`  | Capture viewport width                         |
| `viewport_height`      | no       | `720`   | Capture viewport height                        |
| `show_metadata_footer` | no       | `false` | Include metadata footer in output              |
| `skip_inactivity`      | no       | `true`  | Skip inactive periods during playback          |
| `mouse_tail`           | no       | `true`  | Show mouse trail in replay                     |
