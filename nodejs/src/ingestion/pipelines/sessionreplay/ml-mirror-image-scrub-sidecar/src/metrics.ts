import { Counter, Gauge, Histogram, Registry } from 'prom-client'

import { type UndecodableImageReason } from './image-input.ts'
import { type StageTimings } from './scrub.ts'

export const register = new Registry()

type SourceFormatLabel = 'avif' | 'gif' | 'heif' | 'jpeg' | 'jp2' | 'png' | 'raw' | 'svg' | 'tiff' | 'webp' | 'other'

function sourceFormatLabel(format: string): SourceFormatLabel {
    switch (format) {
        case 'avif':
        case 'gif':
        case 'heif':
        case 'jpeg':
        case 'jp2':
        case 'png':
        case 'raw':
        case 'svg':
        case 'tiff':
        case 'webp':
            return format
        default:
            return 'other'
    }
}

const scrubbed = new Counter({
    name: 'ml_mirror_image_scrub_scrubbed_total',
    help: 'Images scrubbed',
    registers: [register],
})
const failed = new Counter({
    name: 'ml_mirror_image_scrub_failed_total',
    help: 'Transient scrub errors (500) — the consumer retries these',
    registers: [register],
})
const undecodable = new Counter({
    name: 'ml_mirror_image_scrub_undecodable_total',
    help: 'Inputs permanently rejected as undecodable, by bounded reason',
    labelNames: ['reason'],
    registers: [register],
})
const optedOut = new Counter({
    name: 'ml_mirror_image_scrub_opted_out_total',
    help: 'Images skipped because embedded PLUS metadata prohibits AI training',
    registers: [register],
})
const rejected = new Counter({
    name: 'ml_mirror_image_scrub_rejected_total',
    help: 'Requests shed for concurrency (503)',
    registers: [register],
})
const tooLarge = new Counter({
    name: 'ml_mirror_image_scrub_too_large_total',
    help: 'Bodies over the size cap (413) — permanently skipped',
    registers: [register],
})
const aborted = new Counter({
    name: 'ml_mirror_image_scrub_aborted_total',
    help: 'Requests where the consumer hung up before we responded',
    registers: [register],
})
const duration = new Histogram({
    name: 'ml_mirror_image_scrub_duration_seconds',
    help: 'Scrub wall time',
    // Out to 60s: under full admission contention a single scrub's wall time runs to seconds, and a
    // quantile whose true value sits in the +Inf bucket reports the highest finite edge instead. A
    // ceiling that traffic actually reaches reads as a flat line at that ceiling.
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 60],
    registers: [register],
})
const inputBytes = new Histogram({
    name: 'ml_mirror_image_scrub_input_bytes',
    help: 'Encoded size of each image received. Its _sum is the denominator for uniform_frame_bytes_total',
    buckets: [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216],
    registers: [register],
})
const outputBytes = new Histogram({
    name: 'ml_mirror_image_scrub_output_bytes',
    help: 'Scrubbed output size — a collapse toward zero flags an output regression',
    buckets: [64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304],
    registers: [register],
})
// The total duration above says the scrub is slow; these say which stage to attack. Every one of
// these numbers was already being measured per image and thrown away.
const stageDuration = new Histogram({
    name: 'ml_mirror_image_scrub_stage_duration_seconds',
    help: 'Scrub wall time by stage. Sums to roughly the total, so the stage with the largest rate() share is where the CPU goes',
    labelNames: ['stage'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
    registers: [register],
})
// Which decoder we actually pay for. Only formats with a multi-resolution decode (JPEG, WebP) can
// be shrunk on load; PNG has to be fully inflated whatever the target size, so the value of any
// decode-side optimization is bounded by this distribution.
const sourceFormat = new Counter({
    name: 'ml_mirror_image_scrub_source_format_total',
    help: 'Decoded images by bounded source container format',
    labelNames: ['format'],
    registers: [register],
})
// The permanent record's own resolution, which SCRUB_OUT_MAX_PIXELS can now move independently of
// the source. output_bytes alone cannot show it, being confounded by how compressible the content is.
const storedMegapixels = new Histogram({
    name: 'ml_mirror_image_scrub_stored_megapixels',
    help: 'Megapixels of the image actually written, after any SCRUB_OUT_MAX_PIXELS downscale',
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2, 2.56, 4, 8, 16],
    registers: [register],
})
const sourceMegapixels = new Histogram({
    name: 'ml_mirror_image_scrub_source_megapixels',
    help: 'Source megapixels before the SCRUB_MAX_PIXELS downscale, by bounded format. Mass above the SCRUB_MAX_PIXELS budget is the traffic that actually gets downscaled',
    labelNames: ['format'],
    buckets: [0.1, 0.25, 0.5, 1, 2, 2.56, 4, 8, 16, 50],
    registers: [register],
})
// The scrub is a privacy control, so its OUTCOME signals matter as much as its error signals: a
// runaway NSFW gate irreversibly blanking everything, or a detector flatlining at zero (persisting
// un-redacted screenshots), must be distinguishable from healthy operation.
const blanked = new Counter({
    name: 'ml_mirror_image_scrub_blanked_total',
    help: 'Images irreversibly replaced with a blank PNG by the NSFW/gore gate (alert on rate spikes)',
    registers: [register],
})
// Whether blank frames are worth catching earlier (in the Rust collector, before they reach Kafka
// and S3 at all) is a question about volume, not about the scrub. These two answer it: the count
// against scrubbed_total gives the share of calls, and the bytes against input_bytes_sum give the
// share of topic and bucket volume, which is what an upstream skip would actually save. Both count
// only what survives the dedup upstream, since a repeat of the same blank never reaches this service.
const uniformFrames = new Counter({
    name: 'ml_mirror_image_scrub_uniform_frames_total',
    help: 'Frames of a single flat colour, where detection was skipped as provably vacuous',
    registers: [register],
})
const uniformFrameBytes = new Counter({
    name: 'ml_mirror_image_scrub_uniform_frame_bytes_total',
    help: 'Encoded bytes of those frames: the scrub-topic and bucket volume an upstream blank skip would remove',
    registers: [register],
})
const facesRedacted = new Counter({
    name: 'ml_mirror_image_scrub_faces_redacted_total',
    help: 'Face regions solid-filled (alert on a sustained zero rate under traffic: detector outage)',
    registers: [register],
})
const textBoxesRedacted = new Counter({
    name: 'ml_mirror_image_scrub_text_boxes_redacted_total',
    help: 'Text regions solid-filled (alert on a sustained zero rate under traffic: detector outage)',
    registers: [register],
})
const codesRedacted = new Counter({
    name: 'ml_mirror_image_scrub_codes_redacted_total',
    help: 'QR/barcode regions solid-filled',
    registers: [register],
})

// Pool health. Throughput is the product of how many workers are alive and how long each job holds
// one, and neither is visible from the request counters: a pod down to one worker still answers
// every request, just eight times slower, which reads as the load easing off.
const workerRestarts = new Counter({
    name: 'ml_mirror_image_scrub_worker_restarts_total',
    help: 'Replacement attempts after a worker died or wedged (a nonzero rate means jobs are being lost and capacity rebuilt)',
    registers: [register],
})
// Separate from the attempt counter because a replacement that cannot start is retried, so the two
// diverging is what distinguishes a pool rebuilding itself from one failing to.
const workerRestartFailures = new Counter({
    name: 'ml_mirror_image_scrub_worker_restart_failures_total',
    help: 'Replacement attempts that failed to become ready and were themselves retried',
    registers: [register],
})
interface PoolProbe {
    usableWorkers(): number
    queueDepth(): number
}
// Set after the pool starts, so the gauges have to reach for it at scrape time rather than close
// over it at construction.
let pool: PoolProbe | null = null

/** Both values change with every job, far too often to push, so they are sampled when scraped. */
export function trackPool(started: PoolProbe): void {
    pool = started
}

new Gauge({
    name: 'ml_mirror_image_scrub_workers_usable',
    help: 'Inference workers alive and able to serve, against SCRUB_WORKERS. Counts busy ones too: it is capacity, not idleness',
    registers: [register],
    collect() {
        if (pool) {
            this.set(pool.usableWorkers())
        }
    },
})
new Gauge({
    name: 'ml_mirror_image_scrub_queue_depth',
    help: 'Jobs accepted but waiting for a free worker (sustained depth means the pod is undersized, not that a worker is stuck)',
    registers: [register],
    collect() {
        if (pool) {
            this.set(pool.queueDepth())
        }
    },
})

export const ScrubMetrics = {
    incWorkerRestart: () => workerRestarts.inc(),
    incWorkerRestartFailure: () => workerRestartFailures.inc(),
    incScrubbed: () => scrubbed.inc(),
    incFailed: () => failed.inc(),
    incUndecodable: (reason: UndecodableImageReason) => undecodable.labels(reason).inc(),
    incOptedOut: () => optedOut.inc(),
    incRejected: () => rejected.inc(),
    incTooLarge: () => tooLarge.inc(),
    incAborted: () => aborted.inc(),
    startTimer: (): (() => void) => duration.startTimer(),
    observeOutputBytes: (n: number) => outputBytes.observe(n),
    observeScrubOutcome: (t: StageTimings): void => {
        if (t.blanked) {
            blanked.inc()
        }
        if (t.uniform) {
            uniformFrames.inc()
            uniformFrameBytes.inc(t.inputBytes)
        }
        inputBytes.observe(t.inputBytes)
        storedMegapixels.observe(t.storedPixels / 1e6)
        facesRedacted.inc(t.faces)
        textBoxesRedacted.inc(t.textBoxes)
        codesRedacted.inc(t.codes)

        const format = sourceFormatLabel(t.format)
        sourceFormat.labels(format).inc()
        sourceMegapixels.labels(format).observe(t.inputPixels / 1e6)
        stageDuration.labels('decode').observe(t.decodeMs / 1000)
        // Each early return skips the stages below it, and recording their zeros would drag those
        // quantiles toward zero rather than describing the work they do. A uniform frame returns
        // before the gate and every detector, still paying compose and encode; a blanked one returns
        // after the gate but before detection and compose.
        if (t.uniform) {
            stageDuration.labels('compose').observe(t.composeMs / 1000)
            stageDuration.labels('encode').observe(t.encodeMs / 1000)
            return
        }
        stageDuration.labels('nsfw').observe(t.nsfwMs / 1000)
        if (t.blanked) {
            return
        }
        stageDuration.labels('face').observe(t.faceMs / 1000)
        stageDuration.labels('text').observe(t.textMs / 1000)
        stageDuration.labels('codes').observe(t.codesMs / 1000)
        stageDuration.labels('compose').observe(t.composeMs / 1000)
        stageDuration.labels('encode').observe(t.encodeMs / 1000)
    },
}
