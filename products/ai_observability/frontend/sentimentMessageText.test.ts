import { getMessageText } from './sentimentMessageText'

describe('getMessageText', () => {
    it('keeps every block of a message whose content mixes block types', () => {
        const aiInput = [
            {
                role: 'user',
                content: [
                    { type: 'tool_result', content: 'ok' },
                    { type: 'text', text: 'this is broken' },
                ],
            },
        ]

        expect(getMessageText(aiInput, 0)).toBe('ok this is broken')
    })
})
