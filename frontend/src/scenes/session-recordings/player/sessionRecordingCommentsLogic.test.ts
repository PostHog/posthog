import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingCommentsLogic } from 'scenes/session-recordings/player/sessionRecordingCommentsLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { overrideSessionRecordingMocks, setupSessionRecordingTest } from './__mocks__/test-setup'

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

    // Regression test: users without resource-level access to notebooks/comments
    // get a 403 from these side-loads. The replay scene must treat that as an
    // empty result, not bubble it up as an uncaught exception that pollutes
    // error tracking on every recording open.
    it('swallows 403s from comments and notebook side-loads and resolves both loaders empty', async () => {
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation()

        try {
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/1/': {},
                    '/api/projects/:team_id/comments': () => [403, { detail: 'Permission denied' }],
                    '/api/projects/:team/notebooks/recording_comments': () => [
                        403,
                        { detail: 'You do not have viewer access to this resource.' },
                    ],
                },
            })

            logic.actions.loadRecordingComments()
            logic.actions.loadRecordingNotebookComments()

            // Wait for both loaders to settle.
            await new Promise((resolve) => setTimeout(resolve, 100))

            expect(logic.values.sessionCommentsLoading).toBe(false)
            expect(logic.values.sessionNotebookCommentsLoading).toBe(false)
            expect(logic.values.sessionComments).toEqual([])
            expect(logic.values.sessionNotebookComments).toEqual([])
            // The whole point of the fix: the 403 must not surface as a captured exception.
            expect(captureExceptionSpy).not.toHaveBeenCalled()
        } finally {
            captureExceptionSpy.mockRestore()
        }
    })
})
