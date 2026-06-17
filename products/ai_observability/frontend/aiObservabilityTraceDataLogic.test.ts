import posthog from 'posthog-js'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import {
    getEffectiveEventId,
    getInitialFocusEventId,
    getSingleTraceLoadTiming,
    reportTraceNormalizationFailures,
    resolveTraceEventById,
    restoreTree,
} from './aiObservabilityTraceDataLogic'

describe('aiObservabilityTraceDataLogic: restoreTree', () => {
    it('should group a basic trace into a tree', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_generation',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
            },
            {
                event: events[1],
            },
        ])
    })

    it('should build a nested tree', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: '1',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '3',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: '2',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
                aggregation: expect.objectContaining({
                    totalCost: 0,
                    totalLatency: 0,
                    inputTokens: 0,
                    outputTokens: 0,
                }),
                children: [
                    {
                        event: events[1],
                        aggregation: expect.objectContaining({
                            totalCost: 0,
                            totalLatency: 0,
                            inputTokens: 0,
                            outputTokens: 0,
                        }),
                        children: [
                            {
                                event: events[2],
                                children: undefined,
                            },
                        ],
                    },
                ],
            },
        ])
    })

    it('should filter out feedback and metric events', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_feedback',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '3',
                event: '$ai_metric',
                properties: {
                    $ai_parent_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
            },
        ])
    })

    it('should group legacy events without a $ai_parent_id', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_trace_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_span',
                properties: {
                    $ai_trace_id: 'trace',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
                children: undefined,
            },
            {
                event: events[1],
                children: undefined,
            },
        ])
    })

    it('should treat orphaned events as roots when parent does not exist', () => {
        const events: LLMTraceEvent[] = [
            {
                id: '1',
                event: '$ai_span',
                properties: {
                    $ai_span_id: 'span-1',
                    $ai_parent_id: 'missing-parent',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: '2',
                event: '$ai_generation',
                properties: {
                    $ai_span_id: 'span-2',
                    $ai_parent_id: 'span-1',
                },
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        const tree = restoreTree(events, 'trace')
        expect(tree).toEqual([
            {
                event: events[0],
                aggregation: expect.objectContaining({
                    totalCost: 0,
                }),
                children: [
                    {
                        event: events[1],
                    },
                ],
            },
        ])
    })
})

describe('getInitialFocusEventId', () => {
    it('returns $ai_trace event id when present', () => {
        const events: LLMTraceEvent[] = [
            {
                id: 'span-1',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: 'trace-event-1',
                event: '$ai_trace',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        expect(getInitialFocusEventId(events)).toBe('trace-event-1')
    })

    it('returns null for a pseudo-trace so the viewer defaults to the trace root', () => {
        const events: LLMTraceEvent[] = [
            {
                id: 'span-1',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: 'generation-1',
                event: '$ai_generation',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        // No explicit $ai_trace root — should not skip to the first generation
        expect(getInitialFocusEventId(events)).toBeNull()
    })

    it('returns null when a pseudo-trace contains only spans', () => {
        const events: LLMTraceEvent[] = [
            {
                id: 'span-1',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
            {
                id: 'span-2',
                event: '$ai_span',
                properties: {},
                createdAt: '2024-01-01T00:00:00Z',
            },
        ]

        expect(getInitialFocusEventId(events)).toBeNull()
    })

    it('returns null when no events exist', () => {
        expect(getInitialFocusEventId([])).toBeNull()
    })

    it('prioritizes $ai_trace over generation events regardless of order', () => {
        const generationEvent: LLMTraceEvent = {
            id: 'generation-1',
            event: '$ai_generation',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
        }

        const traceEvent: LLMTraceEvent = {
            id: 'trace-event-1',
            event: '$ai_trace',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
        }

        const events: LLMTraceEvent[] = [generationEvent, traceEvent]

        expect(getInitialFocusEventId(events)).toBe('trace-event-1')
    })
})

describe('getEffectiveEventId', () => {
    it('returns eventId when user has selected an event', () => {
        expect(getEffectiveEventId('selected-event-id', 'initial-focus-id')).toBe('selected-event-id')
    })

    it('returns initialFocusEventId when eventId is null', () => {
        expect(getEffectiveEventId(null, 'initial-focus-id')).toBe('initial-focus-id')
    })

    it('returns null when both eventId and initialFocusEventId are null', () => {
        expect(getEffectiveEventId(null, null)).toBeNull()
    })
})

describe('resolveTraceEventById', () => {
    const showableEvents: LLMTraceEvent[] = [
        {
            id: 'event-1',
            event: '$ai_generation',
            properties: {
                $ai_generation_id: 'gen-1',
            },
            createdAt: '2024-01-01T00:00:00Z',
        },
        {
            id: 'event-2',
            event: '$ai_span',
            properties: {
                $ai_span_id: 'span-2',
            },
            createdAt: '2024-01-01T00:00:00Z',
        },
    ]

    it.each([
        ['event id', 'event-1', 'event-1'],
        ['generation id', 'gen-1', 'event-1'],
        ['span id', 'span-2', 'event-2'],
    ])('matches by %s', (_label, eventId, expectedId) => {
        expect(resolveTraceEventById(showableEvents, eventId)?.id).toBe(expectedId)
    })

    it('returns null when no event matches', () => {
        expect(resolveTraceEventById(showableEvents, 'missing')).toBeNull()
    })
})

describe('getSingleTraceLoadTiming', () => {
    it('computes trace age from earliest event timestamp in UTC with query runner duration', () => {
        const trace: LLMTrace = {
            id: 'trace-1',
            createdAt: '2024-01-01T06:00:00Z',
            distinctId: 'user-1',
            events: [
                {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00-05:00',
                },
                {
                    id: 'event-2',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T07:30:00+01:00',
                },
            ],
        }

        const timing = getSingleTraceLoadTiming(trace, '2024-01-01T08:00:00Z', 70)

        expect(timing).toEqual({
            min_trace_timestamp_utc: '2024-01-01T05:00:00.000Z',
            max_trace_timestamp_utc: '2024-01-01T06:30:00.000Z',
            now_timestamp_utc: '2024-01-01T08:00:00.000Z',
            trace_age_minutes: 180,
            trace_timespan_seconds: 5400,
            trace_query_runner_load_duration_ms: 70,
        })
    })

    it('falls back to trace.createdAt when all event timestamps are invalid and duration is missing', () => {
        const trace: LLMTrace = {
            id: 'trace-1',
            createdAt: '2024-01-01T10:00:00Z',
            distinctId: 'user-1',
            events: [
                {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {},
                    createdAt: 'not-a-timestamp',
                },
            ],
        }

        const timing = getSingleTraceLoadTiming(trace, '2024-01-01T11:00:00Z', null)

        expect(timing).toEqual({
            min_trace_timestamp_utc: '2024-01-01T10:00:00.000Z',
            max_trace_timestamp_utc: '2024-01-01T10:00:00.000Z',
            now_timestamp_utc: '2024-01-01T11:00:00.000Z',
            trace_age_minutes: 60,
            trace_timespan_seconds: 0,
            trace_query_runner_load_duration_ms: null,
        })
    })

    it('returns null trace age when now timestamp is invalid, but keeps query runner duration', () => {
        const trace: LLMTrace = {
            id: 'trace-1',
            createdAt: '2024-01-01T10:00:00Z',
            distinctId: 'user-1',
            events: [],
        }

        const timing = getSingleTraceLoadTiming(trace, 'not-a-timestamp', 30)

        expect(timing).toEqual({
            min_trace_timestamp_utc: null,
            max_trace_timestamp_utc: null,
            now_timestamp_utc: null,
            trace_age_minutes: null,
            trace_timespan_seconds: null,
            trace_query_runner_load_duration_ms: 30,
        })
    })

    it('uses earliest valid event timestamp even if trace.createdAt is invalid', () => {
        const trace: LLMTrace = {
            id: 'trace-1',
            createdAt: 'not-a-timestamp',
            distinctId: 'user-1',
            events: [
                {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T10:00:00Z',
                },
                {
                    id: 'event-2',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T09:00:00Z',
                },
            ],
        }

        const timing = getSingleTraceLoadTiming(trace, '2024-01-01T11:00:00Z', 30)

        expect(timing).toEqual({
            min_trace_timestamp_utc: '2024-01-01T09:00:00.000Z',
            max_trace_timestamp_utc: '2024-01-01T10:00:00.000Z',
            now_timestamp_utc: '2024-01-01T11:00:00.000Z',
            trace_age_minutes: 120,
            trace_timespan_seconds: 3600,
            trace_query_runner_load_duration_ms: 30,
        })
    })

    it('keeps null query runner duration when none is provided', () => {
        const trace: LLMTrace = {
            id: 'trace-1',
            createdAt: '2024-01-01T10:00:00Z',
            distinctId: 'user-1',
            events: [],
        }

        const timing = getSingleTraceLoadTiming(trace, '2024-01-01T11:00:00Z', null)

        expect(timing).toEqual({
            min_trace_timestamp_utc: '2024-01-01T10:00:00.000Z',
            max_trace_timestamp_utc: '2024-01-01T10:00:00.000Z',
            now_timestamp_utc: '2024-01-01T11:00:00.000Z',
            trace_age_minutes: 60,
            trace_timespan_seconds: 0,
            trace_query_runner_load_duration_ms: null,
        })
    })
})

describe('reportTraceNormalizationFailures', () => {
    let capture: jest.SpyInstance

    beforeEach(() => {
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
    })

    afterEach(() => {
        capture.mockRestore()
    })

    const traceWith = (events: Partial<LLMTraceEvent>[]): LLMTrace => ({
        id: 'trace-1',
        createdAt: '2024-01-01T00:00:00Z',
        distinctId: 'user-1',
        events: events.map((e, i) => ({
            id: `event-${i}`,
            event: '$ai_generation',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
            ...e,
        })),
    })

    it('captures both unrecognized sides of a generation', () => {
        reportTraceNormalizationFailures(
            traceWith([{ properties: { $ai_input: { weird: 1 }, $ai_output: { odd: 2 } } }])
        )

        expect(capture).toHaveBeenCalledTimes(2)
        expect(capture).toHaveBeenCalledWith('llma message normalization failed', {
            message_keys: ['weird'],
            message_type: 'object',
        })
        expect(capture).toHaveBeenCalledWith('llma message normalization failed', {
            message_keys: ['odd'],
            message_type: 'object',
        })
    })

    it('skips non-generation events', () => {
        reportTraceNormalizationFailures(
            traceWith([{ event: '$ai_span', properties: { $ai_input_state: { weird: 1 } } }])
        )

        expect(capture).not.toHaveBeenCalled()
    })

    it('does not capture a recognized generation', () => {
        reportTraceNormalizationFailures(
            traceWith([
                {
                    properties: {
                        $ai_input: { role: 'user', content: 'hi' },
                        $ai_output_choices: { role: 'assistant', content: 'hello' },
                    },
                },
            ])
        )

        expect(capture).not.toHaveBeenCalled()
    })

    it('prefers $ai_output_choices over $ai_output', () => {
        reportTraceNormalizationFailures(
            traceWith([
                {
                    properties: {
                        $ai_input: { role: 'user', content: 'hi' },
                        $ai_output_choices: { role: 'assistant', content: 'from choices' },
                        $ai_output: { unrecognized: true },
                    },
                },
            ])
        )

        expect(capture).not.toHaveBeenCalled()
    })
})
