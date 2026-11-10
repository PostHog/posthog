import { makeMessage, makeNodeDetail } from './testFixtures'
import { toThread } from './traceThread'
import { ConversationState, ConversationTurn, NodeLoad, NodeSideContent } from './types'

function readyTurns(thread: ConversationState): ConversationTurn[] {
    if (thread.status !== 'ready') {
        throw new Error(`expected a ready thread, got status "${thread.status}"`)
    }
    return thread.turns
}

describe('traceThread', () => {
    const base = { traceId: 'trace-1', createdAt: '2026-09-01T10:15:00Z' }
    const answered = (error: string | null = null): NodeLoad => ({
        status: 'ready',
        node: makeNodeDetail({
            id: 'gen-1',
            error,
            content: {
                input: { kind: 'messages', messages: [makeMessage({ id: 'ask', role: 'user' })] },
                output: { kind: 'messages', messages: [makeMessage({ id: 'answer', role: 'assistant' })] },
            },
        }),
    })

    it('builds one turn for the trace from its thread node', () => {
        const thread = toThread({ ...base, load: answered() })
        expect(thread).toMatchObject({ status: 'ready', activeTurnId: 'trace-1' })
        const [turn] = readyTurns(thread)
        expect(turn).toMatchObject({
            input: { kind: 'messages', messages: [{ id: 'ask', role: 'user' }] },
            output: { kind: 'messages', messages: [{ id: 'answer', role: 'assistant' }] },
            error: null,
        })
    })

    it('keeps a side the server could not read as messages', () => {
        const input: NodeSideContent = { kind: 'json', value: { question: 'Why did my invoice go up?' } }
        const load: NodeLoad = {
            status: 'ready',
            node: makeNodeDetail({
                id: 'gen-1',
                content: {
                    input,
                    output: { kind: 'messages', messages: [makeMessage({ id: 'answer', role: 'assistant' })] },
                },
            }),
        }
        expect(readyTurns(toThread({ ...base, load }))[0].input).toEqual(input)
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
        expect(readyTurns(toThread({ ...base, load: null }))[0]).toMatchObject({
            input: { kind: 'messages', messages: [] },
            output: { kind: 'messages', messages: [] },
        })
    })
})
