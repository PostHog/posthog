import { clipDurationOptions } from './ClipRecording'

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
