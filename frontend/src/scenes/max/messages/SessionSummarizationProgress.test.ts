import { deriveState, formatDuration, formatEta } from './sessionSummarizationProgressUtils'
import type { SessionSummarizationUpdate } from './sessionSummarizationProgressUtils'

describe('SessionSummarizationProgress', () => {
    describe('formatDuration', () => {
        it.each([
            [0, '0s'],
            [30, '30s'],
            [59, '59s'],
            [60, '1m'],
            [90, '1m 30s'],
            [120, '2m'],
            [125, '2m 5s'],
            [3600, '60m'],
            [3661, '61m 1s'],
        ])('formats %i seconds as %s', (input, expected) => {
            expect(formatDuration(input)).toBe(expected)
        })
    })

    describe('formatEta', () => {
        it.each([
            [0, 'almost done'],
            [-5, 'almost done'],
            [3, '~5 seconds remaining'],
            [7, '~5 seconds remaining'],
            [30, '~30 seconds remaining'],
            [55, '~55 seconds remaining'],
            [60, '~1 minute remaining'],
            [90, '~2 minutes remaining'],
            [120, '~2 minutes remaining'],
            [180, '~3 minutes remaining'],
        ])('formats %i remaining seconds as "%s"', (input, expected) => {
            expect(formatEta(input)).toBe(expected)
        })
    })

    describe('deriveState', () => {
        it('returns default state for empty updates', () => {
            const state = deriveState([])
            expect(state.sessions.size).toBe(0)
            expect(state.phase).toBe('fetching_data')
            expect(state.completedCount).toBe(0)
            expect(state.totalCount).toBe(0)
            expect(state.patternsFound).toEqual([])
        })

        it('populates sessions from sessions_discovered update', () => {
            const updates: SessionSummarizationUpdate[] = [
                {
                    type: 'sessions_discovered',
                    sessions: [
                        {
                            id: 'session-1',
                            first_url: 'https://example.com/page1',
                            active_duration_s: 120,
                            distinct_id: 'user-a',
                            start_time: '2025-03-01T10:00:00Z',
                            snapshot_source: 'web',
                        },
                        {
                            id: 'session-2',
                            first_url: 'https://example.com/page2',
                            active_duration_s: 60,
                            distinct_id: 'user-b',
                            start_time: '2025-03-01T11:00:00Z',
                            snapshot_source: 'mobile',
                        },
                    ],
                },
            ]
            const state = deriveState(updates)
            expect(state.sessions.size).toBe(2)
            expect(state.totalCount).toBe(2)
            expect(state.sessions.get('session-1')).toEqual({
                first_url: 'https://example.com/page1',
                active_duration_s: 120,
                distinct_id: 'user-a',
                start_time: '2025-03-01T10:00:00Z',
                snapshot_source: 'web',
                status: 'queued',
            })
            expect(state.sessions.get('session-2')?.snapshot_source).toBe('mobile')
        })

        it('applies status changes from progress updates', () => {
            const updates: SessionSummarizationUpdate[] = [
                {
                    type: 'sessions_discovered',
                    sessions: [
                        {
                            id: 'session-1',
                            first_url: '',
                            active_duration_s: 100,
                            distinct_id: 'user-a',
                            start_time: null,
                            snapshot_source: 'web',
                        },
                    ],
                },
                {
                    type: 'progress',
                    status_changes: [{ id: 'session-1', status: 'summarizing' }],
                    phase: 'watching_sessions',
                    completed_count: 0,
                    total_count: 1,
                    patterns_found: [],
                },
            ]
            const state = deriveState(updates)
            expect(state.sessions.get('session-1')?.status).toBe('summarizing')
            expect(state.phase).toBe('watching_sessions')
        })

        it('tracks completed count and phase through full lifecycle', () => {
            const updates: SessionSummarizationUpdate[] = [
                {
                    type: 'sessions_discovered',
                    sessions: [
                        {
                            id: 's1',
                            first_url: '',
                            active_duration_s: 50,
                            distinct_id: '',
                            start_time: null,
                            snapshot_source: 'web',
                        },
                        {
                            id: 's2',
                            first_url: '',
                            active_duration_s: 80,
                            distinct_id: '',
                            start_time: null,
                            snapshot_source: 'web',
                        },
                    ],
                },
                {
                    type: 'progress',
                    status_changes: [{ id: 's1', status: 'summarizing' }],
                    phase: 'watching_sessions',
                    completed_count: 0,
                    total_count: 2,
                    patterns_found: [],
                },
                {
                    type: 'progress',
                    status_changes: [{ id: 's1', status: 'summarized' }],
                    phase: 'watching_sessions',
                    completed_count: 1,
                    total_count: 2,
                    patterns_found: [],
                },
                {
                    type: 'progress',
                    status_changes: [{ id: 's2', status: 'summarized' }],
                    phase: 'watching_sessions',
                    completed_count: 2,
                    total_count: 2,
                    patterns_found: [],
                },
                {
                    type: 'progress',
                    status_changes: [],
                    phase: 'extracting_patterns',
                    completed_count: 2,
                    total_count: 2,
                    patterns_found: ['Navigation confusion', 'Checkout friction'],
                },
            ]
            const state = deriveState(updates)
            expect(state.completedCount).toBe(2)
            expect(state.totalCount).toBe(2)
            expect(state.phase).toBe('extracting_patterns')
            expect(state.patternsFound).toEqual(['Navigation confusion', 'Checkout friction'])
            expect(state.sessions.get('s1')?.status).toBe('summarized')
            expect(state.sessions.get('s2')?.status).toBe('summarized')
        })

        it('handles progress update for unknown session ID gracefully', () => {
            const updates: SessionSummarizationUpdate[] = [
                {
                    type: 'progress',
                    status_changes: [{ id: 'unknown-session', status: 'summarizing' }],
                    phase: 'watching_sessions',
                    completed_count: 0,
                    total_count: 1,
                    patterns_found: [],
                },
            ]
            const state = deriveState(updates)
            expect(state.sessions.size).toBe(1)
            const session = state.sessions.get('unknown-session')
            expect(session?.status).toBe('summarizing')
            expect(session?.first_url).toBe('')
            expect(session?.active_duration_s).toBe(0)
        })

        it('marks failed sessions correctly', () => {
            const updates: SessionSummarizationUpdate[] = [
                {
                    type: 'sessions_discovered',
                    sessions: [
                        {
                            id: 's1',
                            first_url: '',
                            active_duration_s: 30,
                            distinct_id: '',
                            start_time: null,
                            snapshot_source: 'web',
                        },
                    ],
                },
                {
                    type: 'progress',
                    status_changes: [{ id: 's1', status: 'failed' }],
                    phase: 'watching_sessions',
                    completed_count: 1,
                    total_count: 1,
                    patterns_found: [],
                },
            ]
            const state = deriveState(updates)
            expect(state.sessions.get('s1')?.status).toBe('failed')
            expect(state.completedCount).toBe(1)
        })

        it('does not clear patternsFound when a later update has empty array', () => {
            const updates: SessionSummarizationUpdate[] = [
                {
                    type: 'progress',
                    status_changes: [],
                    phase: 'extracting_patterns',
                    completed_count: 2,
                    total_count: 2,
                    patterns_found: ['Pattern A'],
                },
                {
                    type: 'progress',
                    status_changes: [],
                    phase: 'assigning_patterns',
                    completed_count: 2,
                    total_count: 2,
                    patterns_found: [],
                },
            ]
            const state = deriveState(updates)
            expect(state.patternsFound).toEqual(['Pattern A'])
            expect(state.phase).toBe('assigning_patterns')
        })
    })
})
