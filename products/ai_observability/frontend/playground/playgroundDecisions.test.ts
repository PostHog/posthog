import {
    type PlaygroundQuestion,
    decisionQuestionsDisabledReason,
    messagesToDecisionInput,
    toDecisionQuestionsPayload,
} from './playgroundDecisions'

function question(partial: Partial<PlaygroundQuestion>): PlaygroundQuestion {
    return { id: 'q', type: 'noul', instructions: 'Is it urgent?', options: [], ...partial }
}

function options(...names: string[]): PlaygroundQuestion['options'] {
    return names.map((name, index) => ({ id: `o${index}`, name, description: '' }))
}

describe('playgroundDecisions', () => {
    it.each([
        ['no questions', [], 'Add a question to ask the model'],
        ['a blank question', [question({ instructions: '  ' })], 'Write every question before running'],
        ['an unnamed option', [question({ type: 'choice', options: options('billing', ' ') })], 'Name every option'],
        [
            'duplicate option names',
            [question({ type: 'choice', options: options('billing', 'billing ') })],
            'Give each option of a question a different name',
        ],
        [
            'a one-level scale',
            [question({ type: 'score', options: options('calm') })],
            'A rating question needs 2 to 10 levels',
        ],
        ['a yes/no question with hidden blank options', [question({ options: options('', '') })], null],
        ['valid questions', [question({}), question({ type: 'score', options: options('calm', 'angry') })], null],
    ])('blocks a run with %s', (_name, questions, reason) => {
        expect(decisionQuestionsDisabledReason(questions)).toBe(reason)
    })

    it('keeps tool calls and tool results when a conversation becomes input', () => {
        expect(
            messagesToDecisionInput([
                { role: 'user', content: 'Weather in Paris?' },
                {
                    role: 'assistant',
                    content: '',
                    toolCalls: [{ id: 'call_1', name: 'weather', arguments: '{"city":"Paris"}' }],
                },
                { role: 'tool', content: 'Sunny', toolCallId: 'call_1' },
                { role: 'assistant', content: ' ' },
            ])
        ).toBe(
            'user: Weather in Paris?\n\nassistant: tool call call_1: weather({"city":"Paris"})\n\ntool (result of call_1): Sunny'
        )
    })

    it('keys questions by id and sends option descriptions only for multiple choice', () => {
        const payload = toDecisionQuestionsPayload(
            [
                question({ id: 'urgent', instructions: ' Is {{x}} urgent? ' }),
                question({
                    id: 'topic',
                    type: 'choice',
                    options: [
                        { id: 'a', name: ' billing ', description: 'invoices' },
                        { id: 'b', name: 'bugs', description: ' ' },
                    ],
                }),
                question({
                    id: 'tone',
                    type: 'score',
                    options: [
                        { id: 'c', name: 'calm', description: 'ignored' },
                        { id: 'd', name: 'angry', description: '' },
                    ],
                }),
            ],
            (text) => text.replace('{{x}}', 'this')
        )

        expect(payload).toEqual({
            urgent: { type: 'noul', instructions: 'Is this urgent?' },
            topic: {
                type: 'choice',
                instructions: 'Is it urgent?',
                options: [{ name: 'billing', description: 'invoices' }, { name: 'bugs' }],
            },
            tone: { type: 'score', instructions: 'Is it urgent?', options: [{ name: 'calm' }, { name: 'angry' }] },
        })
    })
})
