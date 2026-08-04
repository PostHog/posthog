import { canEditMessageBody } from './messageMarkdown'

describe('canEditMessageBody', () => {
    // The support editor has no heading, quote, strike or table node, so loading a body that uses
    // one would drop it and the next save would store the note without it. Those bodies are only
    // reachable through the reply API and imports, which accept arbitrary markdown.
    test.each([
        ['plain prose', 'Checked their billing history.', true],
        ['emphasis', '**urgent**: card expired', true],
        ['a bullet list', '- refund issued\n- card expired', true],
        ['a link and inline code', 'see [docs](https://posthog.com/docs) then run `identify()`', true],
        ['a heading', '# Escalation notes', false],
        ['a block quote', '> what the customer said', false],
        ['strikethrough', '~~refunded~~ still pending', false],
        ['a table', '| charge | status |\n| --- | --- |\n| 1 | failed |', false],
        ['an empty body', '   ', false],
    ])('%s is editable: %s', (_name, content, expected) => {
        expect(canEditMessageBody(content, null)).toBe(expected)
    })

    it('always allows a body that already has rich content', () => {
        expect(canEditMessageBody('# not parsed', { type: 'doc', content: [] })).toBe(true)
    })
})
