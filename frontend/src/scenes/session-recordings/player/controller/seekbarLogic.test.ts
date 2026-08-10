import { expectLogic } from 'kea-test-utils'

import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { setupSessionRecordingTest } from '../__mocks__/test-setup'
import { THUMB_OFFSET } from '../utils/playerUtils'
import { seekbarLogic } from './seekbarLogic'

describe('seekbarLogic', () => {
    let logic: ReturnType<typeof seekbarLogic.build>
    let playerLogic: ReturnType<typeof sessionRecordingPlayerLogic.build>

    // Mock recording: recording_duration=11s, so durationMs caps to 11000ms.
    const DURATION_MS = 11000

    const makeSlider = (offsetWidth: number): HTMLDivElement => {
        const div = document.createElement('div')
        Object.defineProperty(div, 'offsetWidth', { value: offsetWidth, configurable: true })
        return div
    }

    beforeEach(async () => {
        setupSessionRecordingTest()
        const props = { sessionRecordingId: '2', playerKey: 'test', blobV2PollingDisabled: true }
        playerLogic = sessionRecordingPlayerLogic(props)
        playerLogic.mount()
        logic = seekbarLogic(props)
        logic.mount()

        await expectLogic(playerLogic).toDispatchActions([
            sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
        ])
        logic.actions.setSlider({ current: makeSlider(100) })
    })

    it.each([
        // ratio 0.5 of the slider → half the total
        {
            description: 'a thumb within the slider maps to a fraction of the total',
            thumbLeftPos: 50 - THUMB_OFFSET,
            expected: DURATION_MS / 2,
        },
        // ratio > 1 (stale thumb or a slider measured while narrow) would run past the total without the clamp
        { description: 'a thumb past the slider width clamps to the total', thumbLeftPos: 200, expected: DURATION_MS },
    ])('$description', ({ thumbLeftPos, expected }) => {
        logic.actions.setThumbLeftPos(thumbLeftPos, false)

        expect(logic.values.scrubbingTime).toBe(expected)
        // scrubbingTimeSeconds is what the drag label renders, so lock it too
        expect(logic.values.scrubbingTimeSeconds).toBe(Math.floor(expected / 1000))
    })
})
