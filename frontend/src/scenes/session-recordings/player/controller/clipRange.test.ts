import { clipDurationOptions, clipWindowSeconds } from './clipRange'

describe('clipRange', () => {
    describe('clipDurationOptions', () => {
        const values = (durationMs: number): number[] => clipDurationOptions(durationMs).map((option) => option.value)

        it('offers only the short durations for a short recording', () => {
            expect(values(30 * 1000)).toEqual([5, 10, 15])
        })

        it('offers minute-long clips once the recording is long enough to need them', () => {
            // A recording too long to export whole is reviewed in parts, and seconds are not a useful part.
            expect(values(2 * 60 * 60 * 1000)).toEqual([5, 10, 15, 60, 300, 900])
        })

        it('leaves out durations longer than the recording itself', () => {
            // A clip that runs past the end would render an empty tail.
            expect(values(3 * 60 * 1000)).toEqual([5, 10, 15, 60])
        })
    })

    describe('clipWindowSeconds', () => {
        it('centers the window on the playhead', () => {
            expect(clipWindowSeconds(600, 3600, 900)).toEqual({ startSeconds: 150, endSeconds: 1050 })
        })

        it.each([
            ['near the end', 3595, { startSeconds: 2700, endSeconds: 3600 }],
            ['at the very end', 3600, { startSeconds: 2700, endSeconds: 3600 }],
        ])('pulls the window back inside the recording %s', (_label, playhead, expected) => {
            // Both the overlay and the export read this. While only the overlay clamped, the exported
            // file started up to half a clip length later than the range shown on screen.
            expect(clipWindowSeconds(playhead as number, 3600, 900)).toEqual(expected)
        })

        it('pushes the window forward at the start of a recording', () => {
            expect(clipWindowSeconds(2, 3600, 900)).toEqual({ startSeconds: 0, endSeconds: 900 })
        })

        it('covers the whole recording when the clip is longer than it', () => {
            expect(clipWindowSeconds(10, 60, 900)).toEqual({ startSeconds: 0, endSeconds: 60 })
        })
    })
})
