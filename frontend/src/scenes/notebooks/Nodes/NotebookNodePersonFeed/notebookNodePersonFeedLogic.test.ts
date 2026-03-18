import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SessionSummaryContent } from 'scenes/session-recordings/player/player-meta/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

const mockSessionSummary1: SessionSummaryContent = {
    segments: [
        {
            index: 0,
            name: 'Login Flow',
            start_event_id: 'event-1',
        },
    ],
    key_actions: [
        {
            segment_index: 0,
            events: [
                {
                    event: 'login page viewed',
                    event_id: 'f7f04516',
                    confusion: false,
                    exception: null,
                    timestamp: '2025-10-01T04:39:00.267000-07:00',
                    window_id: '01994212-ab83-7289-a500-b74ee29f7032',
                    event_type: null,
                    event_uuid: '01991212-c458-76a5-8a7c-e9a3d2f7d37c',
                    session_id: '01990212-ab82-71ae-a250-11d2baa0187',
                    abandonment: false,
                    current_url: 'https://foo.bar.com/login/',
                    description: 'Opened login page',
                    event_index: 0,
                    milliseconds_since_start: 6630,
                },
            ],
        },
    ],
    session_outcome: {
        success: true,
        description: 'User completed login successfully',
    },
}

const mockSessionSummary2: SessionSummaryContent = {
    segments: [
        {
            index: 0,
            name: 'Checkout Process',
            start_event_id: 'event-10',
        },
    ],
    key_actions: [
        {
            segment_index: 0,
            events: [
                {
                    event: 'checkout initiated',
                    event_id: 'a1b2c3d4',
                    confusion: false,
                    exception: null,
                    timestamp: '2025-10-01T05:15:00.123000-07:00',
                    window_id: '01994212-ab83-7289-a500-b74ee29f7033',
                    event_type: null,
                    event_uuid: '01991212-c458-76a5-8a7c-e9a3d2f7d38d',
                    session_id: '01990212-ab82-71ae-a250-11d2baa0188',
                    abandonment: false,
                    current_url: 'https://foo.bar.com/checkout/',
                    description: 'Started checkout process',
                    event_index: 0,
                    milliseconds_since_start: 12450,
                },
                {
                    event: 'payment failed',
                    event_id: 'e5f6g7h8',
                    confusion: false,
                    exception: 'non-blocking',
                    timestamp: '2025-10-01T05:16:30.456000-07:00',
                    window_id: '01994212-ab83-7289-a500-b74ee29f7033',
                    event_type: 'error',
                    event_uuid: '01991212-c458-76a5-8a7c-e9a3d2f7d39e',
                    session_id: '01990212-ab82-71ae-a250-11d2baa0188',
                    abandonment: true,
                    current_url: 'https://foo.bar.com/checkout/payment',
                    description: 'Payment processing failed',
                    event_index: 5,
                    milliseconds_since_start: 102750,
                },
            ],
        },
    ],
    session_outcome: {
        success: false,
        description: 'Payment failed',
    },
}

const mockIndividualSummariesResponse: Record<string, SessionSummaryContent> = {
    'session-1': mockSessionSummary1,
    'session-2': mockSessionSummary2,
    'session-3': mockSessionSummary2,
}

const mockSessionsWithRecording = [
    { sessionId: 'session-1', recording_duration_s: 120 },
    { sessionId: 'session-2', recording_duration_s: 300 },
    { sessionId: 'session-3', recording_duration_s: 180 },
]

const mockSessionsWithoutRecording = [
    { sessionId: 'session-4', recording_duration_s: 0 },
    { sessionId: 'session-5', recording_duration_s: null },
]

const mockMixedSessions = [
    { sessionId: 'session-1', recording_duration_s: 120 },
    { sessionId: 'session-2', recording_duration_s: 0 },
    { sessionId: 'session-3', recording_duration_s: 180 },
    { sessionId: 'session-4', recording_duration_s: null },
]

const mockFailingSessions = [
    { sessionId: 'session-4', recording_duration_s: 120 },
    { sessionId: 'session-5', recording_duration_s: 120 },
]

const failingSessionIds = ['session-4', 'session-5']

describe('notebookNodePersonFeedLogic', () => {
    let logic: ReturnType<typeof notebookNodePersonFeedLogic.build>

    const mountLogic = async (): Promise<void> => {
        logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess'])
    }

    beforeEach(() => {
        initKeaTests()
        useMocks({
            post: {
                [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                    results: mockSessionsWithRecording,
                },
                [`/api/environments/${MOCK_TEAM_ID}/session_summaries/create_session_summaries_individually`]: async (
                    req: any
                ) => {
                    const { session_ids } = await req.json()
                    const sessionId = session_ids[0]
                    if (failingSessionIds.includes(sessionId)) {
                        return [500, { detail: 'Server error' }]
                    }
                    return [200, { [sessionId]: mockIndividualSummariesResponse[sessionId] }]
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
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: () => [500, { detail: 'Internal badaras error' }],
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
        })
    })

    describe('sessionIdsWithRecording selector', () => {
        it('filters sessions with recordings and returns session IDs', async () => {
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSessionsTimelineSuccess'])
                .toMatchValues({
                    sessionIdsWithRecording: ['session-1', 'session-2', 'session-3'],
                })
        })

        it('returns empty array when no sessions have recordings', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithoutRecording,
                    },
                },
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess']).toMatchValues({
                sessionIdsWithRecording: [],
            })
        })

        it('filters mixed sessions correctly', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockMixedSessions,
                    },
                },
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSessionsTimelineSuccess'])
                .toMatchValues({
                    sessionIdsWithRecording: ['session-1', 'session-3'],
                })
        })
    })

    describe('canSummarize selector', () => {
        it('returns true when AI_SESSION_SUMMARY feature flag is enabled', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.AI_SESSION_SUMMARY]: true,
            })

            // Set feature flag to true
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            expect(logic.values.canSummarize).toBe(true)
        })

        it('returns false when AI_SESSION_SUMMARY feature flag is disabled', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.AI_SESSION_SUMMARY]: false,
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            expect(logic.values.canSummarize).toBe(false)
        })
    })

    describe('individual session summarization', () => {
        beforeEach(async () => {
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess'])
        })

        it('successfully summarizes individual session', async () => {
            logic.actions.summarizeSession('session-1')

            await expectLogic(logic)
                .toDispatchActions(['summarizeSession', 'summarizeSessionSuccess'])
                .toMatchValues({
                    summaries: {
                        'session-1': mockSessionSummary1,
                    },
                    summariesLoading: false,
                })
        })

        it('summarizes all sessions with recordings', async () => {
            logic.actions.summarizeSessions()

            await expectLogic(logic)
                .toDispatchActions([
                    'summarizeSessions',
                    'summarizeSession',
                    'summarizeSession',
                    'summarizeSession',
                    'summarizeSessionSuccess',
                ])
                .toMatchValues({
                    summarizingState: 'loading',
                })

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.numSummaries).toBeGreaterThan(0)
        })

        it('sets state to completed when all sessions are processed', async () => {
            logic.actions.summarizeSessions()

            await expectLogic(logic).toDispatchActions(['summarizeSessions'])

            expect(logic.values.summarizingState).toBe('loading')

            await expectLogic(logic)
                .toDispatchActions(['summarizeSessionSuccess', 'summarizeSessionSuccess', 'summarizeSessionSuccess'])
                .toFinishAllListeners()

            expect(logic.values.summarizingState).toBe('completed')
            expect(logic.values.numSummaries).toBe(logic.values.numSessionsWithRecording)
        })

        it('does not call API when no sessions with recordings exist', async () => {
            logic.unmount()
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithoutRecording,
                    },
                },
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess'])

            logic.actions.summarizeSessions()

            await expectLogic(logic).toDispatchActions(['summarizeSessions']).toFinishAllListeners()

            expect(logic.values.summaries).toEqual({})
            expect(logic.values.numSummaries).toBe(0)
        })
    })

    describe('progress tracking', () => {
        beforeEach(async () => {
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess'])
        })

        it('tracks number of sessions with recording', () => {
            expect(logic.values.numSessionsWithRecording).toBe(3)
        })

        it('tracks number of summaries', async () => {
            logic.actions.summarizeSession('session-1')

            await expectLogic(logic).toDispatchActions(['summarizeSessionSuccess'])

            expect(logic.values.numSummaries).toBe(1)
        })

        it('tracks number of sessions processed', async () => {
            logic.actions.summarizeSession('session-1')

            await expectLogic(logic).toDispatchActions(['summarizeSessionSuccess'])

            expect(logic.values.numSummaries).toBe(1)
        })

        it('generates correct progress text', async () => {
            logic.actions.summarizeSession('session-1')

            await expectLogic(logic).toDispatchActions(['summarizeSessionSuccess'])

            expect(logic.values.progressText).toEqual('1 out of 3 sessions analyzed.')
        })
    })

    describe('summarizing state management', () => {
        beforeEach(async () => {
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess'])
        })

        it('starts with idle state', () => {
            expect(logic.values.summarizingState).toBe('idle')
        })

        it('can set summarizing state manually', () => {
            logic.actions.setSummarizingState('loading')
            expect(logic.values.summarizingState).toBe('loading')

            logic.actions.setSummarizingState('completed')
            expect(logic.values.summarizingState).toBe('completed')

            logic.actions.setSummarizingState('idle')
            expect(logic.values.summarizingState).toBe('idle')
        })
    })

    describe('error handling', () => {
        it('tracks failed summarizations in summaryErrors', async () => {
            await mountLogic()
            logic.actions.summarizeSession('session-4')

            await expectLogic(logic).toDispatchActions(['summarizeSession', 'summarizeSessionFailure'])

            expect(logic.values.summaryErrors).toHaveLength(1)
            expect(logic.values.numFailedSummaries).toBe(1)
        })

        it('sets state to completed when all sessions fail', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockFailingSessions,
                    },
                },
            })
            await mountLogic()
            logic.actions.summarizeSessions()

            await expectLogic(logic).toDispatchActions(['summarizeSessions'])

            expect(logic.values.summarizingState).toBe('loading')

            await expectLogic(logic)
                .toDispatchActions(['summarizeSessionFailure', 'summarizeSessionFailure'])
                .toFinishAllListeners()

            expect(logic.values.summarizingState).toBe('completed')
            expect(logic.values.numFailedSummaries).toBe(2)
            expect(logic.values.numSummaries).toBe(0)
        })

        it('sets state to completed when mix of successes and failures', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: [...mockFailingSessions, ...mockSessionsWithRecording],
                    },
                },
            })
            await mountLogic()

            logic.actions.summarizeSessions()

            await expectLogic(logic).toDispatchActions(['summarizeSessions'])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.numSummaries).toBe(3)
            expect(logic.values.numFailedSummaries).toBe(2)
            expect(logic.values.numProcessedSessions).toBe(5)
            expect(logic.values.summarizingState).toBe('completed')
        })

        it('includes failed sessions in numProcessedSessions', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })
            mountLogic()

            logic.actions.summarizeSession('session-4')

            await expectLogic(logic).toDispatchActions(['summarizeSessionFailure'])

            expect(logic.values.numProcessedSessions).toBe(1)
            expect(logic.values.numFailedSummaries).toBe(1)
            expect(logic.values.numSummaries).toBe(0)
        })

        it('generates correct progress text with failures', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })
            mountLogic()

            logic.actions.summarizeSession('session-1')
            await expectLogic(logic).toDispatchActions(['summarizeSessionSuccess'])

            logic.actions.summarizeSession('session-4')
            await expectLogic(logic).toDispatchActions(['summarizeSessionFailure'])

            expect(logic.values.progressText).toEqual('2 out of 3 sessions analyzed.')
        })
    })
})
