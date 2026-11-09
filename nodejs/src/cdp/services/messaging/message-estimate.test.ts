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
})
