import type { TraceNodeDetailApi } from '../../../generated/api.schemas'
import { NodeLoad } from '../types'
import { makeNodeDetail } from './testFixtures'
import { toDatasetItemSource } from './toDatasetItemSource'

const trace = { traceId: 'trace-1', createdAt: '2026-09-01T10:15:00Z' }

function ready(node: TraceNodeDetailApi): NodeLoad {
    return { status: 'ready', node }
}

function withEventUuid(node: TraceNodeDetailApi, uuid: string): TraceNodeDetailApi {
    return node.event ? { ...node, event: { ...node.event, uuid } } : node
}

describe('toDatasetItemSource', () => {
    test.each<[string, NodeLoad, ReturnType<typeof toDatasetItemSource>]>([
        [
            'a generation keys the item by its event uuid and keeps only custom properties as metadata',
            ready(
                withEventUuid(
                    makeNodeDetail({
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
                makeNodeDetail({
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
        ['a step still loading has no source yet', { status: 'loading' }, null],
    ])('%s', (_, load, expected) => {
        expect(toDatasetItemSource({ ...trace, load })).toEqual(expected)
    })
})
