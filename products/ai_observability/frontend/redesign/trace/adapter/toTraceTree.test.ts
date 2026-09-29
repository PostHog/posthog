import { enrich, makeEvent, makeTrace } from './testFixtures'
import { isErrorEvent, toTraceTree } from './toTraceTree'

describe('toTraceTree', () => {
    describe('isErrorEvent', () => {
        it.each([
            ['a populated $ai_error with no flag', { $ai_error: 'boom' }, true],
            ['$ai_is_error: true with no error payload', { $ai_is_error: true }, true],
            ['$ai_is_error: "true" (SDK-serialized boolean)', { $ai_is_error: 'true' }, true],
            ['neither an error payload nor a truthy flag', { $ai_is_error: false }, false],
        ])('%s -> %s', (_description, properties, expected) => {
            expect(isErrorEvent(makeEvent({ id: 'e1', properties }))).toBe(expected)
        })
    })

    const generation = makeEvent({
        id: 'gen-1',
        event: '$ai_generation',
        properties: {
            $ai_span_name: 'draft-answer',
            $ai_model: 'gpt-4.1-mini',
            $ai_input_tokens: 1822,
            $ai_output_tokens: '212',
            $ai_cache_read_input_tokens: 1024,
        },
    })
    const span = makeEvent({ id: 'span-1', event: '$ai_span', properties: { $ai_span_name: 'retrieve-context' } })
    const embedding = makeEvent({ id: 'emb-1', event: '$ai_embedding', properties: { $ai_is_error: true } })

    const tree = toTraceTree(makeTrace({ errorCount: 1 }), [
        enrich(span, [enrich(embedding)], {
            displayLatency: 0.41,
            aggregation: {
                totalCost: null,
                totalLatency: 0.41,
                inputTokens: 18,
                outputTokens: 0,
                hasGenerationChildren: false,
            },
        }),
        enrich(generation, [], { displayTotalCost: 0.0021, displayLatency: 1.88 }),
    ])

    it('wraps events under a root node for the trace itself', () => {
        expect(tree).toHaveLength(1)
        expect(tree[0]).toMatchObject({ id: 'trace-1', kind: 'trace', name: 'answer-billing-question', hasError: true })
        expect(tree[0].children.map((child) => child.id)).toEqual(['span-1', 'gen-1'])
        expect(tree[0].stats).toEqual({
            costUsd: 0.0021,
            inputTokens: 1840,
            outputTokens: 212,
            cacheReadTokens: null,
            latencyMs: 2310,
        })
    })

    it('maps event types to node kinds', () => {
        const [spanNode, generationNode] = tree[0].children
        expect(spanNode.kind).toBe('span')
        expect(spanNode.children[0].kind).toBe('embedding')
        expect(generationNode.kind).toBe('generation')
    })

    it("uses the node's own stats and converts latency to milliseconds", () => {
        const generationNode = tree[0].children[1]
        expect(generationNode.stats).toEqual({
            costUsd: 0.0021,
            inputTokens: 1822,
            outputTokens: 212,
            cacheReadTokens: 1024,
            latencyMs: 1880,
        })
        expect(generationNode.model).toBe('gpt-4.1-mini')
    })

    it('keeps unknown cost null and uses span roll-ups for tokens', () => {
        const spanNode = tree[0].children[0]
        expect(spanNode.stats.costUsd).toBeNull()
        expect(spanNode.stats.inputTokens).toBe(18)
        expect(spanNode.stats.outputTokens).toBeNull()
    })

    it('flags errored events', () => {
        expect(tree[0].children[0].children[0].hasError).toBe(true)
        expect(tree[0].children[1].hasError).toBe(false)
    })
})
