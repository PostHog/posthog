import { timelineTicks } from './timelineTicks'

describe('timelineTicks', () => {
    it.each([
        ['a trace with no duration', 0, [0]],
        ['a short trace', 3539, [0, 1000, 2000, 3000]],
        ['a last tick too close to the end label', 2310, [0, 500, 1000, 1500]],
        ['an agent run', 8374, [0, 2000, 4000, 6000]],
        ['a multi-minute session', 223935, [0, 50000, 100000, 150000]],
        ['a sub-5ms trace', 3, [0, 1, 2]],
        ['a total that is an exact step', 1000, [0, 200, 400, 600, 800]],
    ])('picks rounded ticks for %s', (_label, totalMs, expected) => {
        expect(timelineTicks(totalMs).map((tick) => tick.valueMs)).toEqual(expected)
    })

    it('positions each tick by its share of the total', () => {
        expect(timelineTicks(2000).map((tick) => tick.fraction)).toEqual([0, 0.25, 0.5, 0.75])
    })
})
