import { escapeRawHtmlTags } from './rewriteAgentObjectTags'
import { renderedElements, renderedTags, unsafeMarkup, visibleText, XSS_PAYLOADS } from './xssTestUtils'

const PREFIXES = [
    '',
    'Hello ',
    '> ',
    '- ',
    '1. ',
    '# ',
    '**bold** ',
    '`code` ',
    '```\ncode\n```\n',
    '~~~\ncode\n~~~\n',
    '\n\n',
    '| a | b |\n| - | - |\n| ',
]
const SUFFIXES = ['', ' trailing', '\nnext line', '\n\n```\nafter\n```', ' `code`']

describe('escapeRawHtmlTags against XSS payloads', () => {
    it.each(XSS_PAYLOADS)('the oracle sees raw markup in the unescaped %s', (_, payload) => {
        // Guards the tests below: if the oracle ignored raw HTML, every payload would pass them.
        if (payload.includes('>') && !/^<[a-z]+\//i.test(payload)) {
            expect(unsafeMarkup(payload).length).toBeGreaterThan(0)
        }
    })

    it.each(XSS_PAYLOADS)('leaves no raw markup from %s once escaped', (_, payload) => {
        for (const prefix of PREFIXES) {
            for (const suffix of SUFFIXES) {
                const input = `${prefix}${payload}${suffix}`
                expect({ input, unsafe: unsafeMarkup(escapeRawHtmlTags(input)) }).toEqual({ input, unsafe: [] })
            }
        }
    })

    it.each(XSS_PAYLOADS)('shows %s as the text that was typed', (_, payload) => {
        expect(visibleText(escapeRawHtmlTags(payload))).toBe(payload)
    })

    it('is stable when applied twice', () => {
        for (const [, payload] of XSS_PAYLOADS) {
            const once = escapeRawHtmlTags(payload)
            expect(escapeRawHtmlTags(once)).toBe(once)
        }
    })

    it.each([0, 1, 2, 3, 4, 5, 6])('leaves no raw markup behind %s backslashes', (count) => {
        const input = `${'\\'.repeat(count)}<script>alert(1)</script>`
        expect(unsafeMarkup(escapeRawHtmlTags(input))).toEqual([])
    })

    describe('code boundaries', () => {
        it.each([
            ['after an inline code span', '`a` <script>alert(1)</script>'],
            ['after a double-backtick span', '``a`b`` <script>alert(1)</script>'],
            ['after an unclosed backtick', '`<script>alert(1)</script>'],
            ['between two code spans', '`a` <script>alert(1)</script> `b`'],
            ['after a span with a mismatched run', '`a`` <script>alert(1)</script>'],
            ['after a closed fence', '```\ncode\n```\n<script>alert(1)</script>'],
            ['after a closed tilde fence', '~~~\ncode\n~~~\n<script>alert(1)</script>'],
            ['after a fence closed by a longer run', '```\ncode\n`````\n<script>alert(1)</script>'],
            ['after a fence whose closer is indented by four spaces', '```\ncode\n    ```\n<script>alert(1)</script>'],
            ['inside a blockquote fence', '> ```\n<script>alert(1)</script>\n> ```'],
            ['inside a list item fence', '- ```\n<script>alert(1)</script>\n  ```'],
            ['after an indented fence opener', '    ```\n<script>alert(1)</script>'],
            ['with a backtick in the fence info string', '```js`\n<script>alert(1)</script>\n```'],
            ['with a closer that carries text', '```\ncode\n``` x\n<script>alert(1)</script>'],
            ['across a tilde fence inside a backtick fence', '```\n~~~\n<script>alert(1)</script>\n~~~\n```'],
            ['after code on the same line as a fence marker', '`a` ```\n<script>alert(1)</script>'],
            ['after a span closed on the next line', '`a\nb` <script>alert(1)</script>'],
        ])('leaves no raw markup %s', (_, input) => {
            expect(unsafeMarkup(escapeRawHtmlTags(input))).toEqual([])
        })
    })

    describe('inside code', () => {
        it.each([
            ['an inline code span', 'use `<script>alert(1)</script>` here'],
            ['a fenced block', '```html\n<script>alert(1)</script>\n```'],
            ['a tilde fence', '~~~\n<img src=x onerror=alert(1)>\n~~~'],
            ['an unclosed fence', '```\n<script>alert(1)</script>'],
        ])('keeps %s as inert code text', (_, input) => {
            const escaped = escapeRawHtmlTags(input)
            expect(escaped).toBe(input)
            expect(unsafeMarkup(escaped)).toEqual([])
            expect(visibleText(escaped)).toContain('<')
        })
    })

    describe('autolinks', () => {
        it.each([
            ['an https url', '<https://example.com/path?a=1&b=2>'],
            ['an email address', '<me@example.com>'],
        ])('keeps %s as a link', (_, input) => {
            expect(escapeRawHtmlTags(input)).toBe(input)
            expect(renderedTags(input)).toEqual(['P', 'A'])
        })

        it('does not let a tag ride inside an autolink', () => {
            const input = '<https://example.com/"onmouseover=alert(1)>'
            const anchors = renderedElements(escapeRawHtmlTags(input)).filter((element) => element.tagName === 'A')
            for (const anchor of anchors) {
                expect(anchor.getAttributeNames()).toEqual(['href'])
            }
        })

        it.each([
            ['an element after the autolink', '<https://example.com><script>alert(1)</script>'],
            ['an element inside the autolink text', '<https://example.com/<script>alert(1)</script>>'],
            ['an element after an email autolink', '<me@example.com><img src=x onerror=alert(1)>'],
        ])('escapes %s', (_, input) => {
            const elements = renderedTags(escapeRawHtmlTags(input))
            expect(elements).not.toContain('SCRIPT')
            expect(elements).not.toContain('IMG')
        })
    })
})
