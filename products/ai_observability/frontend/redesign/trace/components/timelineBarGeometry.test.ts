import { timelineBarGeometry } from './timelineBarGeometry'

describe('timelineBarGeometry', () => {
    it.each([
        ['a normal bar', 100, 200, 1000, { leftPercent: 10, widthPercent: 20 }],
        ['a trace with no total duration', 0, 0, 0, { leftPercent: 0, widthPercent: 1.5 }],
        ['a bar starting near the end of the trace', 990, 50, 1000, { leftPercent: 98.5, widthPercent: 1.5 }],
        ['a tiny duration', 0, 1, 1000, { leftPercent: 0, widthPercent: 1.5 }],
        ['a duration longer than the total', 0, 1500, 1000, { leftPercent: 0, widthPercent: 100 }],
    ] as const)('gives %s the geometry %p', (_label, startMs, durationMs, totalMs, expected) => {
        expect(timelineBarGeometry(startMs, durationMs, totalMs)).toEqual(expected)
    })
})
