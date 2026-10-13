import { computeVideoTimestamps, videoTimestampsFromFrames } from '~/session-replay/recording-rasterizer/postprocess'
import { InactivityPeriod } from '~/session-replay/recording-rasterizer/types'

describe('computeVideoTimestamps', () => {
    it('maps active periods to cumulative video time', () => {
        const periods: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 10, active: true },
            { ts_from_s: 10, ts_to_s: 20, active: true },
        ]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(10)
        expect(result[1].recording_ts_from_s).toBe(10)
        expect(result[1].recording_ts_to_s).toBe(20)
    })

    it('inactive periods get zero video duration', () => {
        const periods: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 10, active: true },
            { ts_from_s: 10, ts_to_s: 50, active: false },
            { ts_from_s: 50, ts_to_s: 60, active: true },
        ]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(10)
        // Inactive period points to same position
        expect(result[1].recording_ts_from_s).toBe(10)
        expect(result[1].recording_ts_to_s).toBe(10)
        // Next active period starts where the last active ended
        expect(result[2].recording_ts_from_s).toBe(10)
        expect(result[2].recording_ts_to_s).toBe(20)
    })

    it('handles empty input', () => {
        expect(computeVideoTimestamps([])).toEqual([])
    })

    it('handles single active period', () => {
        const periods: InactivityPeriod[] = [{ ts_from_s: 0, ts_to_s: 30, active: true }]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(30)
    })

    it('handles period with null ts_to_s', () => {
        const periods: InactivityPeriod[] = [{ ts_from_s: 0, ts_to_s: null, active: true }]

        const result = computeVideoTimestamps(periods)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBe(0) // duration is 0 when ts_to_s is null
    })

    it('handles multiple inactive gaps', () => {
        const periods: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 5, active: true },
            { ts_from_s: 5, ts_to_s: 100, active: false },
            { ts_from_s: 100, ts_to_s: 110, active: true },
            { ts_from_s: 110, ts_to_s: 200, active: false },
            { ts_from_s: 200, ts_to_s: 205, active: true },
        ]

        const result = computeVideoTimestamps(periods)

        // 5s active + 10s active + 5s active = 20s total video
        expect(result[0]).toMatchObject({ recording_ts_from_s: 0, recording_ts_to_s: 5 })
        expect(result[1]).toMatchObject({ recording_ts_from_s: 5, recording_ts_to_s: 5 })
        expect(result[2]).toMatchObject({ recording_ts_from_s: 5, recording_ts_to_s: 15 })
        expect(result[3]).toMatchObject({ recording_ts_from_s: 15, recording_ts_to_s: 15 })
        expect(result[4]).toMatchObject({ recording_ts_from_s: 15, recording_ts_to_s: 20 })
    })

    it('preserves original fields', () => {
        const periods: InactivityPeriod[] = [{ ts_from_s: 5, ts_to_s: 10, active: true }]

        const result = computeVideoTimestamps(periods)

        expect(result[0].ts_from_s).toBe(5)
        expect(result[0].ts_to_s).toBe(10)
        expect(result[0].active).toBe(true)
    })
})

describe('videoTimestampsFromFrames', () => {
    // 3 fps, so one frame is 1/3s of video. Playback runs 0-1s, skips to 5s, runs to 6s, and the skip
    // costs the frame it happens on — the frame the predicted mapping never accounts for.
    const periods: InactivityPeriod[] = [
        { ts_from_s: 0, ts_to_s: 1, active: true },
        { ts_from_s: 1, ts_to_s: 5, active: false },
        { ts_from_s: 5, ts_to_s: 6, active: true },
    ]
    const frameSessionMs = [0, 333, 666, 1000, 5000, 5333, 5666]

    it('places a period where the frames actually put it', () => {
        const result = videoTimestampsFromFrames(periods, frameSessionMs, 3)

        expect(result[0].recording_ts_from_s).toBe(0)
        expect(result[0].recording_ts_to_s).toBeCloseTo(1)
        // The resumed stretch starts on frame 4, not frame 3 as the durations alone would say.
        expect(result[2].recording_ts_from_s).toBeCloseTo(4 / 3)
        expect(result[2].recording_ts_to_s).toBeCloseTo(7 / 3)
    })

    it('does not understate the video the way the predicted mapping does', () => {
        const measured = videoTimestampsFromFrames(periods, frameSessionMs, 3)
        const predicted = computeVideoTimestamps(periods)

        const measuredEnd = measured[2].recording_ts_to_s!
        const predictedEnd = predicted[2].recording_ts_to_s!
        expect(measuredEnd).toBeGreaterThan(predictedEnd)
        expect(measuredEnd - predictedEnd).toBeCloseTo(1 / 3)
    })

    it('charges the skipped stretch the frame the skip cost', () => {
        const result = videoTimestampsFromFrames(periods, frameSessionMs, 3)

        expect(result[1].recording_ts_from_s).toBeCloseTo(1)
        expect(result[1].recording_ts_to_s).toBeCloseTo(4 / 3)
        expect(computeVideoTimestamps(periods)[1].recording_ts_to_s).toBe(
            computeVideoTimestamps(periods)[1].recording_ts_from_s
        )
    })

    it('offsets by the frames captured before playback started', () => {
        // Capture runs while the player is still starting, and those frames carry no sample. Without the
        // offset every period is reported early by that many frames.
        const result = videoTimestampsFromFrames(periods, frameSessionMs, 3, 6)

        expect(result[0].recording_ts_from_s).toBeCloseTo(2)
        expect(result[2].recording_ts_to_s).toBeCloseTo(13 / 3)
    })

    it('anchors a stretch with no frames of its own at the frame playback resumed on', () => {
        // A gap shorter than one frame interval is stepped over without any frame landing inside it.
        // The resume frame sits exactly on the gap's end, so the search has to include it.
        const shortGap: InactivityPeriod[] = [
            { ts_from_s: 0, ts_to_s: 1, active: true },
            { ts_from_s: 1, ts_to_s: 1.1, active: false },
            { ts_from_s: 1.1, ts_to_s: 2, active: true },
        ]
        const frames = [0, 333, 666, 1100, 1433]

        const result = videoTimestampsFromFrames(shortGap, frames, 3)

        expect(result[1].recording_ts_from_s).toBeCloseTo(1)
        expect(result[1].recording_ts_from_s).toBeLessThanOrEqual(result[2].recording_ts_from_s!)
    })

    it('holds a stretch the capture started inside to what the file shows', () => {
        // start_offset_s renders from the middle of a session. The stretch still claims session time the
        // file never shows, and a consumer interpolating across it reads every moment inside as later.
        const spanning: InactivityPeriod[] = [{ ts_from_s: 0, ts_to_s: 60, active: true }]
        const frames = [10_000, 10_333, 10_666]

        const result = videoTimestampsFromFrames(spanning, frames, 3)

        expect(result[0].ts_from_s).toBeCloseTo(10)
        expect(result[0].ts_to_s).toBeCloseTo(10.666)
        expect(result[0].recording_ts_from_s).toBe(0)
    })

    it('leaves a stretch the capture covered end to end alone', () => {
        const result = videoTimestampsFromFrames(periods, frameSessionMs, 3)

        expect(result[0].ts_from_s).toBe(0)
        expect(result[0].ts_to_s).toBe(1)
        expect(result[2].ts_from_s).toBe(5)
    })

    it('keeps every stretch of a heavily cut recording in order', () => {
        // One cursor walks periods and samples together. If it over-advances, later stretches are
        // starved of their frames and collapse onto the end of the file.
        const many: InactivityPeriod[] = []
        const frames: number[] = []
        for (let i = 0; i < 100; i++) {
            const base = i * 100
            many.push({ ts_from_s: base, ts_to_s: base + 10, active: true })
            many.push({ ts_from_s: base + 10, ts_to_s: base + 100, active: false })
            for (let f = 0; f < 30; f++) {
                frames.push((base + f / 3) * 1000)
            }
        }

        const result = videoTimestampsFromFrames(many, frames, 3)

        const actives = result.filter((p) => p.active)
        expect(actives).toHaveLength(100)
        for (const period of actives) {
            expect(period.recording_ts_to_s).toBeGreaterThan(period.recording_ts_from_s!)
        }
        for (let i = 1; i < result.length; i++) {
            expect(result[i].recording_ts_from_s).toBeGreaterThanOrEqual(result[i - 1].recording_ts_from_s!)
        }
        expect(actives[99].recording_ts_to_s).toBeCloseTo(frames.length / 3)
    })

    it('falls back to the predicted mapping when capture reported no timeline', () => {
        expect(videoTimestampsFromFrames(periods, [], 3)).toEqual(computeVideoTimestamps(periods))
    })
})
