import { Editor } from '@tiptap/core'

import { MARKDOWN_EXTENSIONS, markdownContent, serializeMarkdown } from './markdownContent'

function load(text: string): Editor {
    return new Editor({ extensions: MARKDOWN_EXTENSIONS, ...markdownContent(text) })
}

describe('markdownContent', () => {
    it.each([
        {
            name: 'escaped punctuation',
            text: '\\[label\\] and \\*not emphasis\\*',
            shown: '[label] and *not emphasis*',
        },
        { name: 'a line that only looks like a heading', text: '\\# not a heading', shown: '# not a heading' },
        { name: 'formatting', text: '# Title\n\nSome **bold** and `a_b*c`', shown: 'TitleSome bold and a_b*c' },
    ])('saves $name back to Markdown that reads the same', ({ text, shown }) => {
        const editor = load(text)
        const saved = serializeMarkdown(editor)

        expect(editor.getText({ blockSeparator: '' })).toEqual(shown)
        expect(load(saved).getJSON()).toEqual(editor.getJSON())
    })

    it('saves literal asterisks left after removing inline code as text, not emphasis', () => {
        const editor = load('a `*literal*` b')
        editor.chain().selectAll().unsetCode().run()

        const reloaded = load(serializeMarkdown(editor))

        expect(reloaded.getText()).toEqual('a *literal* b')
        expect(reloaded.getJSON()).toEqual(editor.getJSON())
    })

    it('keeps an image destination and shows it as a link, never as an image', () => {
        const text = 'see ![chart](https://example.com/chart.png "Weekly")'
        const editor = load(text)

        expect(serializeMarkdown(editor)).toEqual(text)
        expect(editor.getHTML()).toContain('<a href="https://example.com/chart.png"')
        expect(editor.getHTML()).not.toContain('<img')
    })
})
