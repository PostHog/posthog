import { Editor } from '@tiptap/core'

import {
    SURVEY_RICH_TEXT_EXTENSIONS,
    isRichTextCompatibleHtml,
    normalizeRichTextHtml,
    plainTextToHtml,
} from './surveyRichText'

describe('surveyRichText', () => {
    test.each([
        ['', ''],
        ['Tell us more', 'Tell us more'],
        ['a < b & "c"', 'a &lt; b &amp; &quot;c&quot;'],
        ['First line\nSecond line', '<p>First line</p><p>Second line</p>'],
    ])('plainTextToHtml(%j)', (text, expected) => {
        expect(plainTextToHtml(text)).toEqual(expected)
    })

    test.each([
        ['plain text', 'Tell us more', true],
        ['editor output', '<p><strong>Bold</strong> and <em>italic</em></p><p>Next</p>', true],
        ['list', '<ul><li>item</li></ul>', false],
        [
            'editor link',
            '<a href="https://example.com" target="_blank" rel="noopener noreferrer nofollow">link</a>',
            true,
        ],
        ['unsupported tag', '<div>Tell us more</div>', false],
        ['image', '<img src="https://example.com/a.png">', false],
        ['style attribute', '<p style="color: red">Tell us more</p>', false],
    ])('isRichTextCompatibleHtml with %s', (_, html, expected) => {
        expect(isRichTextCompatibleHtml(html)).toEqual(expected)
    })

    test.each([
        ['<p></p>', ''],
        ['<p>Hello <strong>you</strong></p>', 'Hello <strong>you</strong>'],
        ['<p>One</p><p>Two</p>', '<p>One</p><p>Two</p>'],
    ])('normalizeRichTextHtml(%j)', (html, expected) => {
        expect(normalizeRichTextHtml(html)).toEqual(expected)
    })

    it('accepts all formatting that the editor outputs', () => {
        const editor = new Editor({
            extensions: SURVEY_RICH_TEXT_EXTENSIONS,
            content:
                '<p><strong>b</strong> <em>i</em> <u>u</u> <s>s</s> <a href="https://example.com">l</a></p><p>x<br>y</p>',
        })
        const html = editor.getHTML()
        editor.destroy()
        expect(isRichTextCompatibleHtml(html)).toBe(true)
    })
})
