import type { FilterNode } from 'scenes/data-pipelines/event-filtering/eventFilterLogic'

import { CyclotronJobTestInvocationResult, HogFunctionType } from '~/types'

import {
    EventFilterConfig,
    TestEvent,
    getEventFilterStepResult,
    getTestStepResult,
    moveTransformation,
    sortByExecutionOrder,
} from './transformationsFlowUtils'

const transformation = (id: string, execution_order: number | undefined, created_at: string): HogFunctionType =>
    ({ id, name: id, execution_order, created_at, enabled: true, type: 'transformation' }) as HogFunctionType

const EVENT: TestEvent = {
    event: '$pageview',
    uuid: 'event-uuid',
    distinct_id: 'example-user',
    timestamp: '2026-01-01T00:00:00.000Z',
    properties: { $ip: '127.0.0.1' },
}

const CHANGED_EVENT: TestEvent = { ...EVENT, properties: { $ip: null } }

describe('transformationsFlowUtils', () => {
    it.each([
        [
            'orders by execution_order',
            [transformation('b', 2, '2026-01-01'), transformation('a', 1, '2026-01-02')],
            ['a', 'b'],
        ],
        [
            'puts a missing execution_order last',
            [transformation('none', undefined, '2026-01-01'), transformation('set', 5, '2026-01-02')],
            ['set', 'none'],
        ],
        [
            'breaks ties by creation date',
            [transformation('newer', 1, '2026-01-02'), transformation('older', 1, '2026-01-01')],
            ['older', 'newer'],
        ],
    ])('sortByExecutionOrder %s, like the ingestion pipeline', (_, input, expectedIds) => {
        expect(sortByExecutionOrder(input).map((item) => item.id)).toEqual(expectedIds)
    })

    it.each([
        ['moves a step earlier', 'c', -1 as const, { a: 1, c: 2, b: 3 }],
        ['moves a step later', 'a', 1 as const, { b: 1, a: 2, c: 3 }],
        ['refuses to move the first step earlier', 'a', -1 as const, null],
        ['refuses to move the last step later', 'c', 1 as const, null],
    ])('moveTransformation %s', (_, id, offset, expected) => {
        const ordered = [
            transformation('a', undefined, '2026-01-01'),
            transformation('b', undefined, '2026-01-02'),
            transformation('c', undefined, '2026-01-03'),
        ]
        expect(moveTransformation(ordered, id, offset)).toEqual(expected)
    })

    it.each([
        ['changed', { status: 'success', result: CHANGED_EVENT }, 'changed', CHANGED_EVENT],
        ['unchanged', { status: 'success', result: EVENT }, 'unchanged', EVENT],
        ['skipped by filters', { status: 'skipped', result: EVENT }, 'skipped', EVENT],
        ['dropped', { status: 'success', result: null }, 'dropped', null],
        ['failed, which keeps the event like ingestion does', { status: 'error', result: null }, 'error', EVENT],
    ])('getTestStepResult maps a %s response', (_, response, expectedOutcome, expectedOutput) => {
        const result = getTestStepResult(EVENT, { logs: [], ...response } as CyclotronJobTestInvocationResult)
        expect(result).toMatchObject({ outcome: expectedOutcome, output: expectedOutput })
    })

    const DROP_PAGEVIEWS: FilterNode = {
        type: 'or',
        children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: '$pageview' }],
    }

    it.each([
        ['a live filter that matches drops the event', { mode: 'live', filter_tree: DROP_PAGEVIEWS }, 'dropped', null],
        [
            'a dry run filter that matches keeps the event',
            { mode: 'dry_run', filter_tree: DROP_PAGEVIEWS },
            'counted',
            EVENT,
        ],
        ['a disabled filter keeps the event', { mode: 'disabled', filter_tree: DROP_PAGEVIEWS }, 'kept', EVENT],
        [
            'a live filter that does not match keeps the event',
            {
                mode: 'live',
                filter_tree: {
                    type: 'or',
                    children: [{ type: 'condition', field: 'distinct_id', operator: 'exact', value: 'bot' }],
                },
            },
            'kept',
            EVENT,
        ],
    ])('getEventFilterStepResult: %s', (_, eventFilter, expectedOutcome, expectedOutput) => {
        expect(getEventFilterStepResult(EVENT, eventFilter as EventFilterConfig | null)).toMatchObject({
            outcome: expectedOutcome,
            output: expectedOutput,
        })
    })
})
