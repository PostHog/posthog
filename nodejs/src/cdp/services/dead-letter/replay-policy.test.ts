import { Message } from 'node-rdkafka'

import type { InvocationBuildFailure } from '../../types'
import {
    partitionReplayFailures,
    readDeadLetterRecord,
    readParkedEvent,
    replayTargetIds,
    replayTargetKinds,
} from './replay-policy'

describe('replay policy', () => {
    const message = (headers: Record<string, string>, value: string | null = '{"team_id":2}'): Message =>
        ({
            value: value === null ? null : Buffer.from(value),
            headers: Object.entries(headers).map(([key, header]) => ({ [key]: Buffer.from(header) })),
            topic: 'cdp_events_dlq',
            partition: 0,
            offset: 1,
            size: 0,
        }) as unknown as Message

    it('reads a record from its headers without touching the payload', () => {
        const record = readDeadLetterRecord(
            message({
                dlq_step: 'inputs',
                dlq_reason: 'Invalid arguments',
                dlq_team_id: '2',
                dlq_hog_function_ids: 'fn-1,fn-2',
                dlq_hog_flow_ids: 'flow-1',
                dlq_kinds: 'hog_function,hog_flow',
            })
        )

        expect(record).toEqual({
            hogFunctionIds: ['fn-1', 'fn-2'],
            hogFlowIds: ['flow-1'],
            kinds: ['hog_function', 'hog_flow'],
        })
    })

    it.each([
        ['no step header', message({})],
        ['a step header but no value', message({ dlq_step: 'inputs' }, null)],
    ])('returns null for %s', (_label, built) => {
        expect(readDeadLetterRecord(built)).toBeNull()
    })

    it('targets only the sources a record names, across both kinds', () => {
        const record = readDeadLetterRecord(
            message({ dlq_step: 'filter', dlq_hog_function_ids: 'fn-1', dlq_hog_flow_ids: 'flow-1' })
        )!

        expect(replayTargetIds(record)).toEqual(new Set(['fn-1', 'flow-1']))
    })

    it('targets only the kind that threw when a record names a kind but no source', () => {
        // The pipeline that did not throw already queued its invocations for this event.
        const record = readDeadLetterRecord(message({ dlq_step: 'process', dlq_kinds: 'hog_flow' }))!

        expect(replayTargetIds(record)).toBeNull()
        expect(replayTargetKinds(record)).toEqual(new Set(['hog_flow']))
    })

    it('targets every kind when a record names none, because nothing was built', () => {
        expect(replayTargetKinds(readDeadLetterRecord(message({ dlq_step: 'parse' }))!)).toBeNull()
    })

    it('targets everything when a record names nothing, because nothing was built', () => {
        const record = readDeadLetterRecord(message({ dlq_step: 'process' }))!

        expect(replayTargetIds(record)).toBeNull()
    })

    it('does not rebuild an event whose payload names no team', () => {
        expect(readParkedEvent(message({ dlq_step: 'parse' }, '{"uuid":"abc"}'))).toBeNull()
    })

    it('throws on bytes that will not parse, rather than reporting nothing to replay', () => {
        // The worker blocks on a record it cannot rebuild. Returning null here would read as
        // "nothing to do" and commit the offset past an event that was never replayed.
        expect(() => readParkedEvent(message({ dlq_step: 'parse' }, '{"broken'))).toThrow()
    })

    it('rebuilds an event from parked bytes', () => {
        expect(readParkedEvent(message({ dlq_step: 'inputs' }, '{"team_id":2,"uuid":"abc"}'))).toMatchObject({
            team_id: 2,
            uuid: 'abc',
        })
    })
})

describe('partitionReplayFailures', () => {
    const failure = (overrides: Partial<InvocationBuildFailure>): InvocationBuildFailure => ({
        sourceId: 'fn-1',
        sourceKind: 'hog_function',
        step: 'inputs',
        error: 'boom',
        ...overrides,
    })

    it('blocks on a failure that is ours, so the offset is not committed past a lost delivery', () => {
        const { blocking, unreplayable } = partitionReplayFailures([
            failure({ errorClass: 'drift' }),
            failure({ errorClass: 'bug' }),
            failure({ errorClass: 'platform' }),
            failure({}),
        ])

        expect(blocking).toHaveLength(4)
        expect(unreplayable).toBe(0)
    })

    it('passes over a failure no replay can clear, so one record cannot wedge the worker', () => {
        const { blocking, unreplayable } = partitionReplayFailures([
            failure({ errorClass: 'data' }),
            failure({ errorClass: 'limit' }),
            failure({ errorClass: 'legacy' }),
        ])

        expect(blocking).toHaveLength(0)
        expect(unreplayable).toBe(3)
    })

    it('still blocks when only one of a mixed batch is ours', () => {
        const { blocking, unreplayable } = partitionReplayFailures([
            failure({ errorClass: 'data' }),
            failure({ sourceId: 'fn-2', errorClass: 'drift' }),
        ])

        expect(blocking).toEqual([expect.objectContaining({ sourceId: 'fn-2' })])
        expect(unreplayable).toBe(1)
    })
})
