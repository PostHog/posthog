import { playbackSpeedHotkey, stepPlaybackSpeed } from './sessionRecordingPlayerLogic'

describe('playback speed shortcuts', () => {
    it.each([
        [0.5, undefined],
        [1, '1'],
        [1.5, undefined],
        [2, '2'],
        [3, '3'],
        [4, '4'],
        [8, '8'],
        [16, undefined],
    ])('gives %sx the digit that prints it: %s', (speed, expected) => {
        expect(playbackSpeedHotkey(speed)).toEqual(expected)
    })

    it.each([
        [1, 1, 1.5],
        [1, -1, 0.5],
        [0.5, -1, 0.5],
        [16, 1, 16],
        [2.5, 1, 1.5],
    ] as [number, 1 | -1, number][])('steps %sx by %s to %sx', (speed, direction, expected) => {
        expect(stepPlaybackSpeed(speed, direction)).toEqual(expected)
    })
})
