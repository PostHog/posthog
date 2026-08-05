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

describe('observeScrubOutcome', () => {
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
})
