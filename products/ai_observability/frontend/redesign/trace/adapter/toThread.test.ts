import { makeEvent, makeTrace } from './testFixtures'
import { toThread } from './toThread'

describe('toThread', () => {
    const generation = makeEvent({
        id: 'gen-1',
        event: '$ai_generation',
        createdAt: '2026-09-01T10:15:02Z',
        properties: {
            $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
            $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
        },
    })

    it('builds one turn for the trace from its user-visible generation', () => {
        const thread = toThread(makeTrace({ events: [generation] }), {}, 7)
        expect(thread.activeTurnId).toBe('trace-1')
        expect(thread.turns).toHaveLength(1)
        expect(thread.turns[0].messages.map((m) => [m.role, m.sourceNodeId])).toEqual([
            ['user', 'gen-1'],
            ['assistant', 'gen-1'],
        ])
        expect(thread.turns[0].error).toBeNull()
    })

    it('carries the error of a failed generation on its turn', () => {
        const failed = makeEvent({
            id: 'gen-3',
            event: '$ai_generation',
            properties: {
                $ai_input: [{ role: 'user', content: 'Describe this photo.' }],
                $ai_is_error: true,
                $ai_error: 'Model does not support image input',
            },
        })
        expect(toThread(makeTrace({ events: [failed] }), {}, 7).turns[0].error).toBe(
            'Model does not support image input'
        )
    })

    it('uses offloaded content from the cache', () => {
        const offloaded = makeEvent({ id: 'gen-2', event: '$ai_generation', properties: {} })
        const thread = toThread(
            makeTrace({ events: [offloaded] }),
            {
                'gen-2': {
                    input: [{ role: 'user', content: 'Hi' }],
                    output: [{ role: 'assistant', content: 'Hello' }],
                    tools: null,
                },
            },
            7
        )
        expect(thread.turns[0].messages).toHaveLength(2)
    })

    it('gives an empty turn when the trace has no generation', () => {
        expect(toThread(makeTrace({ events: [makeEvent({ id: 's1' })] }), {}, 7).turns[0].messages).toEqual([])
    })
})
