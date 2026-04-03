import { droppedFramesForDelta } from './framerateTracker'

describe('droppedFramesForDelta', () => {
    it.each([
        // Normal frames — no drops
        { deltaMs: 16.67, expected: 0, label: 'exactly one frame at 60fps' },
        { deltaMs: 14, expected: 0, label: 'slightly fast frame' },
        { deltaMs: 20, expected: 0, label: 'slightly slow frame still rounds to 1' },

        // Dropped frames
        { deltaMs: 33.34, expected: 1, label: 'one dropped frame (~2x normal)' },
        { deltaMs: 50, expected: 2, label: 'two dropped frames (~3x normal)' },
        { deltaMs: 100, expected: 5, label: 'five dropped frames (~6x normal)' },
        { deltaMs: 500, expected: 29, label: 'half-second stall' },
        { deltaMs: 1000, expected: 59, label: 'full-second stall' },

        // Edge cases
        { deltaMs: 0, expected: 0, label: 'zero delta' },
        { deltaMs: 1, expected: 0, label: 'sub-millisecond delta' },
    ])('$label (delta=$deltaMs ms) → $expected dropped', ({ deltaMs, expected }) => {
        expect(droppedFramesForDelta(deltaMs)).toBe(expected)
    })
})
