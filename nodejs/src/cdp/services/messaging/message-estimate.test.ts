import { estimateMessageBytes } from './message-estimate'

describe('estimateMessageBytes', () => {
    const withoutBodies = estimateMessageBytes([])

    it.each([
        ['an ASCII body', 'x'.repeat(57), 78],
        ['a body of two-byte characters', 'é'.repeat(57), 156],
        ['an empty body', '', 0],
    ])('counts %s at its base64 transfer size', (_name, body, transferBytes) => {
        expect(estimateMessageBytes([], [body]) - withoutBodies).toBe(transferBytes)
    })

    it.each([
        ['an ASCII subject', 'x'.repeat(42), 75],
        ['a subject one byte past an encoded word', 'x'.repeat(43), 150],
        ['a subject of two-byte characters', 'é'.repeat(21), 75],
        ['an empty subject', '', 0],
    ])('counts %s at its folded encoded-word size', (_name, subject, headerBytes) => {
        expect(estimateMessageBytes([], [], subject) - withoutBodies).toBe(headerBytes)
    })
})
