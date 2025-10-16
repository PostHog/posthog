import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionSummaryResponse } from '~/types'

import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

const mockSessionSummaryResponse: SessionSummaryResponse = {
    patterns: [
        {
            pattern_id: 1,
            pattern_name: 'High Error Rate',
            pattern_description: 'Users encountering multiple errors during checkout process',
            severity: 'high' as const,
            indicators: ['Multiple 4xx errors', 'Long response times', 'Failed transactions'],
            events: [],
            stats: {
                occurences: 15,
                sessions_affected: 8,
                sessions_affected_ratio: 0.4,
                segments_success_ratio: 0.2,
            },
        },
        {
            pattern_id: 2,
            pattern_name: 'Successful Navigation',
            pattern_description: 'Users successfully completing their intended workflow',
            severity: 'low' as const,
            indicators: ['Smooth page transitions', 'Quick load times', 'Successful form submissions'],
            events: [],
            stats: {
                occurences: 25,
                sessions_affected: 12,
                sessions_affected_ratio: 0.6,
                segments_success_ratio: 0.9,
            },
        },
    ],
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

describe('notebookNodePersonFeedLogic', () => {
    let logic: ReturnType<typeof notebookNodePersonFeedLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('sessions loading', () => {
        it('loads sessions timeline on mount', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })

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
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })

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
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.AI_SESSION_SUMMARY]: true,
            })

            // Set feature flag to true
            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            expect(logic.values.canSummarize).toBe(true)
        })

        it('returns false when AI_SESSION_SUMMARY feature flag is disabled', async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.AI_SESSION_SUMMARY]: false,
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            expect(logic.values.canSummarize).toBe(false)
        })
    })

    describe('session summarization', () => {
        beforeEach(async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                    [`/api/environments/${MOCK_TEAM_ID}/session_summaries/create_session_summaries`]: jest
                        .fn()
                        .mockResolvedValue([200, mockSessionSummaryResponse]),
                },
            })

            logic = notebookNodePersonFeedLogic({ personId: 'test-person-123' })
            logic.mount()

            // Wait for sessions to load
            await expectLogic(logic).toDispatchActions(['loadSessionsTimelineSuccess'])
        })

        it('successfully summarizes sessions', async () => {
            logic.actions.summarizeSessions()

            await expectLogic(logic)
                .toDispatchActions(['summarizeSessions', 'summarizeSessionsSuccess'])
                .toMatchValues({
                    sessionSummary: mockSessionSummaryResponse,
                    summarizingState: 'success',
                    sessionSummaryLoading: false,
                })
        })

        it('handles summarization failure', async () => {
            // Override the mock to return an error
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                    [`/api/environments/${MOCK_TEAM_ID}/session_summaries/create_session_summaries`]: jest
                        .fn()
                        .mockResolvedValue([500, { detail: 'Internal server error' }]),
                },
            })

            logic.actions.summarizeSessions()

            await expectLogic(logic)
                .toDispatchActions(['summarizeSessions', 'summarizeSessionsFailure'])
                .toMatchValues({
                    sessionSummary: null,
                    summarizingState: 'error',
                    sessionSummaryLoading: false,
                })
        })

        it('sets loading state during summarization', async () => {
            // Mock a delayed response
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                    [`/api/projects/${MOCK_TEAM_ID}/session_summaries/create_session_summaries`]: () =>
                        new Promise((resolve) => {
                            setTimeout(() => resolve([200, mockSessionSummaryResponse]), 100)
                        }),
                },
            })

            logic.actions.summarizeSessions()

            // Should immediately set loading state
            expect(logic.values.summarizingState).toBe('loading')
            expect(logic.values.sessionSummaryLoading).toBe(true)

            await expectLogic(logic).toDispatchActions(['summarizeSessionsSuccess']).toMatchValues({
                sessionSummary: mockSessionSummaryResponse,
                summarizingState: 'success',
                sessionSummaryLoading: false,
            })
        })

        it('does not summarize when no sessions with recordings exist', async () => {
            // Setup logic with no recording sessions
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

            await expectLogic(logic)
                .toDispatchActions(['summarizeSessions', 'summarizeSessionsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    sessionSummary: null,
                    summarizingState: 'success',
                    sessionSummaryLoading: false,
                })
        })
    })

    describe('summarizing state management', () => {
        beforeEach(async () => {
            useMocks({
                post: {
                    [`/api/environments/${MOCK_TEAM_ID}/query/`]: {
                        results: mockSessionsWithRecording,
                    },
                },
            })

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

            logic.actions.setSummarizingState('success')
            expect(logic.values.summarizingState).toBe('success')

            logic.actions.setSummarizingState('error')
            expect(logic.values.summarizingState).toBe('error')

            logic.actions.setSummarizingState('idle')
            expect(logic.values.summarizingState).toBe('idle')
        })
    })
})
