import { maybeAddPreheaderToEmail } from './preheader'

const HIDDEN_STYLE = 'display:none !important;visibility:hidden;mso-hide:all;font-size:1px;'

describe('maybeAddPreheaderToEmail', () => {
    it('adds the preheader after the opening body tag', () => {
        expect(maybeAddPreheaderToEmail('<html><body class="x"><p>Hi</p></body></html>', 'Preview')).toMatch(
            /^<html><body class="x"><span style="display:none[^"]*">Preview<\/span><p>Hi<\/p>/
        )
    })

    it.each([
        [
            'a hidden table cell, as the editor writes it',
            `<body><table><tr><td style="${HIDDEN_STYLE}">\n      Warning: bad joke.\n    </td></tr></table><p>Hi</p></body>`,
            'Warning: bad joke.',
        ],
        [
            'a hidden element whose text is written with different entities',
            `<body><div style="${HIDDEN_STYLE}">We've got tools &amp; hedgehogs</div><p>Hi</p></body>`,
            'We&#39;ve got tools &amp; hedgehogs',
        ],
        [
            'a hidden element with an upper-case tag and spaced style',
            '<BODY><DIV STYLE="display : none">Preview</DIV><p>Hi</p></BODY>',
            'Preview',
        ],
        [
            'a hidden element preceded only by markup without text',
            `<body><div class="spacer"></div><table><tr><td style="${HIDDEN_STYLE}">Preview</td></tr></table><p>Hi</p></body>`,
            'Preview',
        ],
        [
            'a hidden element revealed to non-outlook clients by a conditional comment',
            `<body><!--[if !mso]><!--><div style="${HIDDEN_STYLE}">Preview</div><!--<![endif]--><p>Hi</p></body>`,
            'Preview',
        ],
        [
            'a hidden element whose text differs from the preheader only in case',
            `<body><div style="${HIDDEN_STYLE}">PREVIEW</div><p>Hi</p></body>`,
            'Preview',
        ],
        [
            'a hidden element preceded by a stylesheet',
            `<body><style>p{color:red}</style><div style="${HIDDEN_STYLE}">Preview</div><p>Hi</p></body>`,
            'Preview',
        ],
    ])('leaves the html alone when it already has the preheader in %s', (_case, html, preheader) => {
        expect(maybeAddPreheaderToEmail(html, preheader)).toBe(html)
    })

    it.each([
        [
            'hidden text that differs from the preheader',
            `<body><div style="${HIDDEN_STYLE}">Something else</div></body>`,
            'Preview',
        ],
        ['the same text in a visible element', '<body><h1 style="color:#000">Preview</h1></body>', 'Preview'],
        [
            'a hidden element that holds more than the preheader',
            `<body><div style="${HIDDEN_STYLE}"><b>Preview</b></div></body>`,
            'Preview',
        ],
        [
            'hidden markup that matches a preheader written as escaped markup',
            `<body><div style="${HIDDEN_STYLE}"><b>Preview</b></div></body>`,
            '&lt;b&gt;Preview&lt;/b&gt;',
        ],
        [
            'the preheader in a hidden element commented out',
            `<body><!-- <div style="${HIDDEN_STYLE}">Preview</div> --><p>Hi</p></body>`,
            'Preview',
        ],
        [
            'the preheader in a hidden element only outlook renders',
            `<body><!--[if mso]><div style="${HIDDEN_STYLE}">Preview</div><![endif]--><p>Hi</p></body>`,
            'Preview',
        ],
        [
            'a hidden copy of the preheader after visible body text',
            `<body><p>Body first</p><div style="${HIDDEN_STYLE}">Preview</div></body>`,
            'Preview',
        ],
    ])('still adds the preheader when the html has %s', (_case, html, preheader) => {
        const result = maybeAddPreheaderToEmail(html, preheader)
        expect(result).toMatch(new RegExp(`^<body><span style="display:none[^"]*">${preheader}</span>`))
        expect(result.endsWith(html.slice('<body>'.length))).toBe(true)
    })

    it('returns the html untouched without a preheader', () => {
        expect(maybeAddPreheaderToEmail('<body><p>Hi</p></body>', '')).toBe('<body><p>Hi</p></body>')
        expect(maybeAddPreheaderToEmail('<body><p>Hi</p></body>')).toBe('<body><p>Hi</p></body>')
    })
})
