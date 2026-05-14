import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingCommentsLogic } from 'scenes/session-recordings/player/sessionRecordingCommentsLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { setupSessionRecordingTest } from './__mocks__/test-setup'

jest.mock('./snapshot-processing/DecompressionWorkerManager')

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('sessionRecordingCommentsLogic', () => {
    let logic: ReturnType<typeof sessionRecordingCommentsLogic.build>
    let dataLogic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>
    let capturedCommentsQuery: URLSearchParams | null = null

    beforeEach(() => {
        capturedCommentsQuery = null
        setupSessionRecordingTest({
            getMocks: {
                '/api/environments/:team_id/session_recordings/1/': {},
                '/api/projects/:team_id/comments': (req) => {
                    capturedCommentsQuery = req.url.searchParams
                    return [200, { results: [] }]
                },
            },
        })
        featureFlagLogic.mount()

        dataLogic = sessionRecordingDataCoordinatorLogic(playerLogicProps)
        dataLogic.mount()

        logic = sessionRecordingCommentsLogic(playerLogicProps)
        logic.mount()
    })

    // Regression test: without the scope query param, the Postgres composite
    // index (team_id, scope, item_id, ...) cannot be used selectively and the
    // request times out on teams with large Comment tables (408 errors).
    it('passes scope=Replay when loading recording comments', async () => {
        await expectLogic(dataLogic, () => {
            dataLogic.actions.maybeLoadRecordingMeta()
        }).toDispatchActions(['loadRecordingCommentsSuccess'])

        expect(capturedCommentsQuery).not.toBeNull()
        expect(capturedCommentsQuery?.get('scope')).toBe('Replay')
        expect(capturedCommentsQuery?.get('item_id')).toBe('1')
    })
})
