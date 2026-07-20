import { Counter, Histogram, Registry } from 'prom-client'

import { type StageTimings } from './scrub.ts'

export const register = new Registry()

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
    help: 'Inputs sharp could not decode (422) — permanently skipped, never retried',
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
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
    registers: [register],
})
const outputBytes = new Histogram({
    name: 'ml_mirror_image_scrub_output_bytes',
    help: 'Scrubbed output size — a collapse toward zero flags an output regression',
    buckets: [64, 256, 1024, 4096, 16384, 65536],
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

export const ScrubMetrics = {
    incScrubbed: () => scrubbed.inc(),
    incFailed: () => failed.inc(),
    incUndecodable: () => undecodable.inc(),
    incRejected: () => rejected.inc(),
    incTooLarge: () => tooLarge.inc(),
    incAborted: () => aborted.inc(),
    startTimer: (): (() => void) => duration.startTimer(),
    observeOutputBytes: (n: number) => outputBytes.observe(n),
    observeScrubOutcome: (t: StageTimings): void => {
        if (t.blanked) {
            blanked.inc()
        }
        facesRedacted.inc(t.faces)
        textBoxesRedacted.inc(t.textBoxes)
        codesRedacted.inc(t.codes)
    },
}
