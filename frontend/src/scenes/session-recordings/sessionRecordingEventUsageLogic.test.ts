import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { SessionPlayerData, SessionRecordingType } from '~/types'

import { sessionRecordingEventUsageLogic } from './sessionRecordingEventUsageLogic'

describe('sessionRecordingEventUsageLogic', () => {
    let logic: ReturnType<typeof sessionRecordingEventUsageLogic.build>

    const playerData = {
        durationMs: 1000,
        sessionRecordingId: 'abc',
    } as SessionPlayerData

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        logic = sessionRecordingEventUsageLogic()
        logic.mount()
    })

    // snapshot_source is caller-controlled at runtime, so anything outside the
    // allowlist must be normalized to keep the metric series bounded
    it.each([
        ['web', 'web'],
        ['mobile', 'mobile'],
        ['some-arbitrary-caller-value', 'unknown'],
        [undefined, 'unknown'],
    ])('reports recording loaded metric with snapshot_source %p as %p', async (rawSource, expectedLabel) => {
        const metadata = { snapshot_source: rawSource } as unknown as SessionRecordingType

        await expectLogic(logic, () => {
            logic.actions.reportRecordingLoaded(playerData, metadata)
        }).toFinishAllListeners()

        expect(posthog.metrics?.count).toHaveBeenCalledWith('replay_player_recordings_loaded', 1, {
            attributes: { snapshot_source: expectedLabel },
        })
    })
})
