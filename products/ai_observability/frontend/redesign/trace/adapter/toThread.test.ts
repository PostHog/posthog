import { ConversationState, ConversationTurn, NodeLoad } from '../types'
import { makeNodeDetail } from './testFixtures'
import { toThread } from './toThread'

function readyTurns(thread: ConversationState): ConversationTurn[] {
    if (thread.status !== 'ready') {
        throw new Error(`expected a ready thread, got status "${thread.status}"`)
    }
    return thread.turns
}

describe('toThread', () => {
    const base = { traceId: 'trace-1', createdAt: '2026-09-01T10:15:00Z', teamId: 7 }
    const answered = (error: string | null = null): NodeLoad => ({
        status: 'ready',
        node: makeNodeDetail({
            id: 'gen-1',
            error,
            properties: {
                $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
                $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
            },
            ioKeys: { input: '$ai_input', output: '$ai_output_choices' },
        }),
    })

    it('builds one turn for the trace from its thread node', () => {
        const thread = toThread({ ...base, load: answered() })
        expect(thread).toMatchObject({ status: 'ready', activeTurnId: 'trace-1' })
        const turns = readyTurns(thread)
        expect(turns[0].messages.map((message) => [message.role, message.sourceNodeId])).toEqual([
            ['user', 'gen-1'],
            ['assistant', 'gen-1'],
        ])
        expect(turns[0].error).toBeNull()
    })

    it('carries the error of a failed generation on its turn', () => {
        expect(readyTurns(toThread({ ...base, load: answered('Model does not support image input') }))[0].error).toBe(
            'Model does not support image input'
        )
    })

    it.each<[string, NodeLoad, ConversationState]>([
        ['loading', { status: 'loading' }, { status: 'loading' }],
        [
            'failed',
            { status: 'error', failure: 'failed' },
            { status: 'error', message: 'The conversation could not be loaded. Reload the page to try again.' },
        ],
    ])('a thread whose node is %s', (_name, load, expected) => {
        expect(toThread({ ...base, load })).toEqual(expected)
    })

    it('gives an empty turn when the trace has no thread node', () => {
        expect(readyTurns(toThread({ ...base, load: null }))[0].messages).toEqual([])
    })
})
