import { ConversationState, ConversationTurn } from '../types'
import { makeEvent, makeTrace } from './testFixtures'
import { toThread } from './toThread'

function readyTurns(thread: ConversationState): ConversationTurn[] {
    if (thread.status !== 'ready') {
        throw new Error(`expected a ready thread, got status "${thread.status}"`)
    }
    return thread.turns
}

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
        expect(thread).toMatchObject({ status: 'ready', activeTurnId: 'trace-1' })
        const turns = readyTurns(thread)
        expect(turns).toHaveLength(1)
        expect(turns[0].messages.map((m) => [m.role, m.sourceNodeId])).toEqual([
            ['user', 'gen-1'],
            ['assistant', 'gen-1'],
        ])
        expect(turns[0].error).toBeNull()
    })

    it('carries the error of a failed generation on its turn', () => {
        const failed = makeEvent({
            id: 'gen-3',
            event: '$ai_generation',
            properties: {
                $ai_input: [{ role: 'user', content: 'Describe this photo.' }],
                $ai_output_choices: [],
                $ai_is_error: true,
                $ai_error: 'Model does not support image input',
            },
        })
        expect(readyTurns(toThread(makeTrace({ events: [failed] }), {}, 7))[0].error).toBe(
            'Model does not support image input'
        )
    })

    it.each([
        ['is loading while its offloaded content is not cached', {}, { status: 'loading' }],
        [
            'uses its offloaded content once cached',
            {
                'gen-2': {
                    input: [{ role: 'user', content: 'Hi' }],
                    output: [{ role: 'assistant', content: 'Hello' }],
                    tools: null,
                },
            },
            { status: 'ready', turns: [{ messages: [{ role: 'user' }, { role: 'assistant' }] }] },
        ],
    ])('an offloaded generation %s', (_name, cache, expected) => {
        const offloaded = makeEvent({ id: 'gen-2', event: '$ai_generation', properties: {} })
        expect(toThread(makeTrace({ events: [offloaded] }), cache, 7)).toMatchObject(expected)
    })

    it('gives an empty turn when the trace has no generation', () => {
        expect(readyTurns(toThread(makeTrace({ events: [makeEvent({ id: 's1' })] }), {}, 7))[0].messages).toEqual([])
    })
})
