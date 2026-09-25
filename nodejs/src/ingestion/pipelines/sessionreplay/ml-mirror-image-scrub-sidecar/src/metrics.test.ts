import { ScrubMetrics, register } from './metrics.ts'
import { type StageTimings } from './scrub.ts'

function timings(over: Partial<StageTimings> = {}): StageTimings {
    return {
        decodeMs: 5,
        nsfwMs: 0,
        faceMs: 0,
        textMs: 0,
        codesMs: 0,
        composeMs: 1,
        encodeMs: 2,
        totalMs: 8,
        blanked: false,
        uniform: false,
        faceVacuous: false,
        codesVacuous: false,
        faces: 0,
        textBoxes: 0,
        codes: 0,
        format: 'png',
        inputPixels: 1000,
        inputBytes: 500,
        storedPixels: 1000,
        ...over,
    }
}

async function stageCount(stage: string): Promise<number> {
    const metric = (await register.getMetricsAsJSON()).find(
        (m) => m.name === 'ml_mirror_image_scrub_stage_duration_seconds'
    )
    const values = (metric as { values: { metricName?: string; labels: Record<string, string>; value: number }[] })
        .values
    return values.find((v) => v.metricName?.endsWith('_count') && v.labels.stage === stage)?.value ?? 0
}

async function sourceFormatLabels(): Promise<string[]> {
    const metric = (await register.getMetricsAsJSON()).find(
        (candidate) => candidate.name === 'ml_mirror_image_scrub_source_format_total'
    )
    return (metric as { values: { labels: Record<string, string> }[] }).values.map((value) => value.labels.format)
}

async function undecodableReasonLabels(): Promise<string[]> {
    const metric = (await register.getMetricsAsJSON()).find(
        (candidate) => candidate.name === 'ml_mirror_image_scrub_undecodable_total'
    )
    return (metric as { values: { labels: Record<string, string> }[] }).values.map((value) => value.labels.reason)
}

async function vacuousDetectorCount(detector: string): Promise<number> {
    const metric = (await register.getMetricsAsJSON()).find(
        (candidate) => candidate.name === 'ml_mirror_image_scrub_vacuous_detector_total'
    )
    const values = (metric as { values: { labels: Record<string, string>; value: number }[] }).values
    return values.find((value) => value.labels.detector === detector)?.value ?? 0
}

describe('observeScrubOutcome', () => {
    beforeEach(() => register.resetMetrics())

    // A skipped detector took no time, so its zero must not land in the stage quantiles, and the
    // skip must be countable on its own because it is what the size bound saves.
    it('counts a skipped detector instead of timing it', async () => {
        ScrubMetrics.observeScrubOutcome(timings({ faceVacuous: true, codesVacuous: true }))

        expect(await stageCount('face')).toBe(0)
        expect(await stageCount('codes')).toBe(0)
        expect(await stageCount('text')).toBe(1)
        expect(await vacuousDetectorCount('face')).toBe(1)
        expect(await vacuousDetectorCount('codes')).toBe(1)
    })

    // A frame that returned early never ran the stages below its exit, so recording their zeros
    // reports work that did not happen and pulls every one of those quantiles toward zero. The
    // damage scales with how common the early exit is, so it lands hardest exactly when the
    // dashboard is being used to judge whether the early exit is worth having.
    it('records only the stages that ran', async () => {
        ScrubMetrics.observeScrubOutcome(timings({ uniform: true }))

        expect(await stageCount('decode')).toBe(1)
        expect(await stageCount('encode')).toBe(1)
        for (const skipped of ['nsfw', 'face', 'text', 'codes']) {
            expect(await stageCount(skipped)).toBe(0)
        }

        ScrubMetrics.observeScrubOutcome(timings({ blanked: true, nsfwMs: 3 }))

        expect(await stageCount('nsfw')).toBe(1)
        for (const skipped of ['face', 'text', 'codes']) {
            expect(await stageCount(skipped)).toBe(0)
        }
    })

    it.each(['bmp', 'vendor-specific'])(
        'coalesces unsupported source format %s into the bounded other label',
        async (format) => {
            ScrubMetrics.observeScrubOutcome(timings({ format }))

            expect(await sourceFormatLabels()).toEqual(['other'])
        }
    )

    it('records bounded undecodable reasons', async () => {
        ScrubMetrics.incUndecodable('decode_failed')
        ScrubMetrics.incUndecodable('unsupported_format')

        expect(await undecodableReasonLabels()).toEqual(['decode_failed', 'unsupported_format'])
    })
})
