import type { TraceNodeRawApi } from '../../../generated/api.schemas'
import { makeRawNode } from '../testFixtures'
import { RawLoad } from '../types'
import { toDatasetItemSource } from './toDatasetItemSource'

const trace = { traceId: 'trace-1', createdAt: '2026-09-01T10:15:00Z' }

function ready(raw: TraceNodeRawApi): RawLoad {
    return { status: 'ready', raw }
}

function withEventUuid(raw: TraceNodeRawApi, uuid: string): TraceNodeRawApi {
    return raw.event ? { ...raw, event: { ...raw.event, uuid } } : raw
}

describe('toDatasetItemSource', () => {
    test.each<[string, RawLoad | undefined, ReturnType<typeof toDatasetItemSource>]>([
        [
            'a generation keys the item by its event uuid and keeps only custom properties as metadata',
            ready(
                withEventUuid(
                    makeRawNode({
                        id: 'sdk-span-id',
                        properties: {
                            $ai_input: [{ role: 'user', content: 'hi' }],
                            $ai_output_choices: [{ role: 'assistant', content: 'hello' }],
                            $ai_model: 'gpt-4o',
                            conversation_tier: 'pro',
                        },
                        ioKeys: { input: '$ai_input', output: '$ai_output_choices' },
                    }),
                    'event-uuid-1'
                )
            ),
            {
                traceId: 'trace-1',
                timestamp: '2026-09-01T10:15:00Z',
                sourceId: 'event-uuid-1',
                input: [{ role: 'user', content: 'hi' }],
                output: [{ role: 'assistant', content: 'hello' }],
                metadata: { conversation_tier: 'pro' },
            },
        ],
        [
            'the trace root is keyed by the trace id and carries its state without metadata',
            ready(
                makeRawNode({
                    id: 'trace-1',
                    kind: 'trace',
                    properties: { $ai_input_state: { q: 'refund?' }, $ai_output_state: { a: 'yes' }, plan: 'pro' },
                    ioKeys: { input: '$ai_input_state', output: '$ai_output_state' },
                })
            ),
            {
                traceId: 'trace-1',
                timestamp: '2026-09-01T10:15:00Z',
                sourceId: 'trace-1',
                input: { q: 'refund?' },
                output: { a: 'yes' },
            },
        ],
        [
            'a trace without an event of its own is keyed by the trace id with no input or output',
            ready(makeRawNode({ id: 'trace-1', kind: 'trace', withEvent: false })),
            {
                traceId: 'trace-1',
                timestamp: '2026-09-01T10:15:00Z',
                sourceId: 'trace-1',
                input: undefined,
                output: undefined,
            },
        ],
        ['a step still loading has no source yet', { status: 'loading' }, null],
        ['a step never read has no source yet', undefined, null],
        ['a step whose read failed has no source', { status: 'error', failure: 'failed' }, null],
    ])('%s', (_, raw, expected) => {
        expect(toDatasetItemSource({ ...trace, raw })).toEqual(expected)
    })
})
