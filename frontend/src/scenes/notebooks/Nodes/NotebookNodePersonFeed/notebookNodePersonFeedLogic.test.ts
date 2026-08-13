import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

const mockSessionsWithRecording = [
    { sessionId: 'session-1', recording_duration_s: 120 },
    { sessionId: 'session-2', recording_duration_s: 300 },
    { sessionId: 'session-3', recording_duration_s: 180 },
]

describe('notebookNodePersonFeedLogic', () => {
    // The suite deliberately mixes failing sessions (session-4/5 return 500s) into
    // most tests to exercise summarization failure handling — skip the loader logging.
    beforeAll(silenceKeaLoadersErrors)
    afterAll(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof notebookNodePersonFeedLogic.build>

    beforeEach(() => {
        initKeaTests()
        useMocks({
            post: {
                [`/api/environments/${MOCK_TEAM_ID}/query/:kind/`]: {
                    results: mockSessionsWithRecording,
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('sessions loading', () => {
        it('loads sessions timeline on mount', async () => {
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSessionsTimeline', 'loadSessionsTimelineSuccess'])
                .toMatchValues({
                    sessions: mockSessionsWithRecording,
                    sessionsLoading: false,
                })
        })

        it('handles sessions loading failure', async () => {
            silenceKeaLoadersErrors()
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/:kind/`]: () => [
                        500,
                        { detail: 'Internal badaras error' },
                    ],
                },
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSessionsTimeline', 'loadSessionsTimelineFailure'])
                .toMatchValues({
                    sessions: null,
                    sessionsLoading: false,
                })
            resumeKeaLoadersErrors()
        })
    })
})
