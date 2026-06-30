import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { sessionPlaybackLogic } from './sessionPlaybackLogic'

describe('sessionPlaybackLogic', () => {
    let logic: ReturnType<typeof sessionPlaybackLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        logic = sessionPlaybackLogic({ sessionId: 's1' })
        logic.mount()
        logic.actions.setTimeline(6000)
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('seeks to an absolute position and pauses', async () => {
        await expectLogic(logic, () => logic.actions.seek(2500)).toMatchValues({ currentMs: 2500, playing: false })
    })

    it('advances on tick scaled by speed and stops at the end', async () => {
        logic.actions.setSpeed(2)
        logic.actions.play()
        logic.actions.tick(1000) // 1000ms * 2x = 2000ms
        await expectLogic(logic).toMatchValues({ currentMs: 2000, playing: true })
        logic.actions.tick(10_000) // clamps to duration, then pauses
        await expectLogic(logic).toMatchValues({ currentMs: 6000, playing: false })
    })

    it('re-syncs a longer duration without rewinding the current position', async () => {
        logic.actions.seek(2500)
        // A late trace load extends the timeline; playback position is preserved.
        await expectLogic(logic, () => logic.actions.setTimeline(8000)).toMatchValues({
            currentMs: 2500,
            durationMs: 8000,
        })
    })

    it('clamps the current position when the duration shrinks', async () => {
        logic.actions.seek(5000)
        await expectLogic(logic, () => logic.actions.setTimeline(3000)).toMatchValues({
            currentMs: 3000,
            durationMs: 3000,
        })
    })
})
