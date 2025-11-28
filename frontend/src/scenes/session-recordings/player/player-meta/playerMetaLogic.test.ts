import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingType } from '~/types'

import recordingEventsJson from '../../__mocks__/recording_events_query'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../../__mocks__/recording_snapshots'

jest.mock('../snapshot-processing/DecompressionWorkerManager')

const playerProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('playerMetaLogic', () => {
    let logic: ReturnType<typeof playerMetaLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                '/api/environments/:team_id/session_recordings/:id/snapshots/': (_, res, ctx) =>
                    res(ctx.text(snapshotsAsJSONLines())),
            },
            post: {
                '/api/environments/:team_id/query': recordingEventsJson,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        logic = playerMetaLogic(playerProps)
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', () => {
            expectLogic(logic).toMount([
                sessionRecordingDataCoordinatorLogic(playerProps),
                sessionRecordingPlayerLogic(playerProps),
            ])
        })
        it('starts with loading state', () => {
            expectLogic(logic).toMatchValues({
                loading: true,
            })
        })
    })

    describe('loading state', () => {
        it('stops loading after meta load is successful', async () => {
            const session: SessionRecordingType = {
                id: '1',
            } as SessionRecordingType
            await expectLogic(logic, () => {
                sessionRecordingDataCoordinatorLogic(playerProps).actions.loadRecordingMeta()
                logic.actions.maybeLoadPropertiesForSessions([session])
            })
                .toDispatchActions(['loadRecordingMetaSuccess', 'loadPropertiesForSessionsSuccess'])
                .toMatchValues({ loading: false })
        })
    })
})
