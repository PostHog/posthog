import { contentBlockText, renderContentBlocks } from './FallbackMcpToolRenderer'

describe('renderContentBlocks', () => {
    it('unwraps the ACP { type: content, content: { type: text, text } } envelope', () => {
        const blocks = [{ type: 'content', content: { type: 'text', text: 'hello world' } }]
        expect(renderContentBlocks(blocks)).toEqual('hello world')
    })

    it('reads a flat { type: text, text } block directly', () => {
        expect(contentBlockText({ type: 'text', text: 'done' })).toEqual('done')
    })

    it('joins multiple blocks with newlines', () => {
        const blocks = [
            { type: 'content', content: { type: 'text', text: 'one' } },
            { type: 'text', text: 'two' },
        ]
        expect(renderContentBlocks(blocks)).toEqual('one\ntwo')
    })

    it('falls back to pretty JSON for a non-text block', () => {
        const block = { type: 'content', content: { type: 'image', data: 'abc' } }
        expect(contentBlockText(block)).toEqual(JSON.stringify(block, null, 2))
    })
})
