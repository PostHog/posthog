import { BODY_MAX_LENGTH, UNSUBSCRIBE_TOKENS_CHECKED, clickableHrefs, preferencesTokensInBody } from './clickable-links'

const manyAttributes = Array.from({ length: 1_000 }, (_, index) => `data-${index}="x"`).join(' ')

describe('clickableHrefs', () => {
    it.each([
        ['an anchor', '<p>News</p><a href="https://example.com/bye">Unsubscribe</a>', ['https://example.com/bye']],
        [
            'an anchor nested in a table',
            '<table><tr><td><p><a href="https://example.com/bye">Unsubscribe</a></p></td></tr></table>',
            ['https://example.com/bye'],
        ],
        ['an anchor inside an HTML comment', '<!-- <a href="https://example.com/bye">Unsubscribe</a> -->', []],
        ['the address in another attribute of an anchor', '<a title="https://example.com/bye">Unsubscribe</a>', []],
        ['the address on an element that is not an anchor', '<link href="https://example.com/bye">', []],
        ['the address as text', '<p>https://example.com/bye</p>', []],
        [
            'an anchor with an encoded ampersand',
            '<a href="https://example.com/bye?a=1&amp;b=2">Unsubscribe</a>',
            ['https://example.com/bye?a=1&b=2'],
        ],
        [
            'an anchor in an SVG drawing',
            '<svg><a href="https://example.com/bye"><text>Unsubscribe</text></a></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an SVG anchor with an href after its xlink:href',
            '<svg><a xlink:href="https://example.com/bye" href="https://example.com/news"><text>News</text></a></svg>',
            ['https://example.com/news'],
        ],
        [
            'an SVG anchor with an href before its xlink:href',
            '<svg><a href="https://example.com/news" xlink:href="https://example.com/bye"><text>News</text></a></svg>',
            ['https://example.com/news'],
        ],
        [
            'an SVG anchor with only an xlink:href',
            '<svg><a xlink:href="https://example.com/bye"><text>Unsubscribe</text></a></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a script',
            '<script>document.write(\'<a href="https://example.com/bye">Unsubscribe</a>\')</script>',
            [],
        ],
        [
            'an anchor inside a style block',
            '<style>/* <a href="https://example.com/bye">Unsubscribe</a> */</style>',
            [],
        ],
        ['an anchor inside a text area', '<textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>', []],
        ['an anchor inside the title', '<title><a href="https://example.com/bye">Unsubscribe</a></title>', []],
        ['an anchor inside noscript', '<noscript><a href="https://example.com/bye">Unsubscribe</a></noscript>', []],
        ['an anchor inside a template', '<template><a href="https://example.com/bye">Unsubscribe</a></template>', []],
        [
            'an anchor inside a script after an SVG drawing',
            '<svg></svg><script>document.write(\'<a href="https://example.com/bye">Unsubscribe</a>\')</script>',
            [],
        ],
        [
            'an anchor after an element named like an object property',
            '<constructor></constructor><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a script in an SVG foreign object',
            '<svg><foreignObject><script>document.write(\'<a href="https://example.com/bye">Unsubscribe</a>\')</script></foreignObject></svg>',
            [],
        ],
        [
            'an anchor with only xlink:href in an SVG foreign object',
            '<svg><foreignObject><a xlink:href="https://example.com/bye">Unsubscribe</a></foreignObject></svg>',
            [],
        ],
        [
            'an anchor with only xlink:href after an unclosed SVG foreign object',
            '<svg><foreignObject></svg><a xlink:href="https://example.com/bye">Unsubscribe</a>',
            [],
        ],
        [
            'an anchor inside the title of an SVG drawing',
            '<svg><title><a href="https://example.com/bye">Unsubscribe</a></title></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a script in an SVG title',
            '<svg><title><script><a href="https://example.com/bye">Unsubscribe</a></script></title></svg>',
            [],
        ],
        [
            'an anchor inside a script in an SVG description',
            '<svg><desc><script><a href="https://example.com/bye">Unsubscribe</a></script></desc></svg>',
            [],
        ],
        [
            'an anchor inside a script after an HTML tag breaks out of an SVG drawing',
            '<svg><p><script><a href="https://example.com/bye">Unsubscribe</a></script></p></svg>',
            [],
        ],
        [
            'an anchor inside a script in an HTML MathML annotation-xml element',
            '<math><annotation-xml encoding="text/html"><script><a href="https://example.com/bye">Unsubscribe</a></script></annotation-xml></math>',
            [],
        ],
        [
            'an SVG anchor nested inside an SVG foreign object',
            '<svg><foreignObject><svg><a xlink:href="https://example.com/bye"><text>Unsubscribe</text></a></svg></foreignObject></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside CDATA in an SVG style element',
            '<svg><style><![CDATA[</style><a href="https://example.com/bye">Unsubscribe</a>]]></style></svg>',
            [],
        ],
        [
            'an anchor after a self-closing style tag inside an SVG drawing',
            '<svg><style/><a href="https://example.com/bye"><text>Unsubscribe</text></a></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a style block in a MathML text element',
            '<math><mtext><style>/* <a href="https://example.com/bye">Unsubscribe</a> */</style></mtext></math>',
            [],
        ],
        [
            'an anchor after a closed script',
            '<script>let a = 1</script><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an SVG drawing',
            '<svg><circle r="1"></circle></svg><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor in CDATA after a nested SVG drawing',
            '<svg><svg></svg><![CDATA[> <a href="https://example.com/bye">Unsubscribe</a>]]></svg>',
            [],
        ],
        [
            'an anchor in CDATA in a MathML formula',
            '<math><![CDATA[> <a href="https://example.com/bye">Unsubscribe</a>]]></math>',
            [],
        ],
        [
            'an anchor inside a select',
            '<select><option><a href="https://example.com/bye">Unsubscribe</a></option></select>',
            [],
        ],
        [
            'an anchor after an input implicitly closes a select',
            '<select><input><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after a nested select implicitly closes a select',
            '<select><select><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a textarea that implicitly closes a select',
            '<select><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor after a closed textarea that implicitly closed a select',
            '<select><textarea></textarea><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a script in a select',
            '<select><script>document.write(\'</select><a href="https://example.com/bye">Unsubscribe</a>\')</script></select>',
            [],
        ],
        [
            'an anchor inside a script that a select hides from the raw text start tag before it',
            '<select><xmp></select><script></xmp></select><a href="https://example.com/bye">Unsubscribe</a></script>',
            [],
        ],
        [
            'an anchor after a template with an unclosed select',
            '<template><select></template><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a self-closing template',
            '<template/><a href="https://example.com/bye">Unsubscribe</a>',
            [],
        ],
        [
            'an anchor before a frameset inside a comment',
            '<a href="https://example.com/bye">Unsubscribe</a><!-- <frameset> -->',
            ['https://example.com/bye'],
        ],
        [
            'an anchor reconstructed across repeated blocks after an SVG drawing',
            '<svg></svg><div><a href="https://example.com/a"></div>' +
                '<div>x</div>'.repeat(100) +
                '<a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/a', 'https://example.com/bye'],
        ],
    ])('returns the hrefs a reader can click in %s', (_name, html, hrefs) => {
        expect(clickableHrefs(html)).toEqual(hrefs)
    })

    it.each([
        ['longer than the tokenizer reads', ' '.repeat(BODY_MAX_LENGTH)],
        ['with more attributes on one tag than the tokenizer reads', `<div ${manyAttributes}></div>`],
        [
            'after an SVG drawing with more attributes on one tag than the tokenizer reads',
            `<svg></svg><div ${manyAttributes}></div>`,
        ],
    ])('finds no anchor in markup %s', (_name, filler) => {
        expect(clickableHrefs(filler + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([])
    })

    it.each([
        ['deeply nested markup', '<div>'.repeat(40_000)],
        ['an SVG drawing and a table with foster-parented elements', '<svg></svg><table>' + '<i></i>'.repeat(1_000)],
        [
            'an SVG drawing and repeated active formatting elements',
            '<svg></svg>' + '<div><table><object><b></table></div>'.repeat(20_000),
        ],
        [
            'a MathML annotation-xml element with a large encoding attribute followed by many tags',
            '<math><annotation-xml encoding="' + 'A'.repeat(750_000) + '">' + '<x></x>'.repeat(100_000) + '</math>',
        ],
        [
            'an SVG element with a large tag name followed by many end tags',
            '<svg><' + 'a'.repeat(750_000) + '>' + '</x>'.repeat(100_000) + '</svg>',
        ],
        [
            'many nested MathML text integration points followed by unmatched SVG end tags',
            '<math><mtext>'.repeat(50_000) + '</svg>'.repeat(50_000),
        ],
    ])('finds the anchor in linear time after %s', (_name, filler) => {
        expect(clickableHrefs(filler + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([
            'https://example.com/bye',
        ])
    })
})

describe('preferencesTokensInBody', () => {
    it('extracts the preferences token without re-parsing reconstructed copies of a long href', () => {
        const longHref = `https://example.com/${'a'.repeat(1_000_000)}`
        const html =
            `<svg></svg><div><a href="${longHref}"></div>` +
            '<div>x</div>'.repeat(20_000) +
            '<a href="https://app.posthog.com/messaging-preferences/tok-1/">Unsubscribe</a>'
        expect(preferencesTokensInBody({ html }, 'https://app.posthog.com')).toEqual(['tok-1'])
    })

    it('extracts the preferences token without IDNA-normalizing long Unicode hostnames', () => {
        const unicodeHost = Array.from({ length: 4_000 }, (_, i) => String.fromCodePoint(0x4e00 + i)).join('')
        const unicodeLinks = Array.from({ length: 160 }, (_, i) => `<a href="https://${unicodeHost}/p${i}">x</a>`).join(
            ''
        )
        const specialSchemeLinks = [
            `<a href="https:\\\\${unicodeHost}/p">x</a>`,
            `<a href="https://\t/${unicodeHost}/p">x</a>`,
            `<a href="https:${unicodeHost}/p">x</a>`,
        ].join('')
        const html =
            unicodeLinks +
            specialSchemeLinks +
            '<a href="https://app.posthog.com/messaging-preferences/tok-1/">Unsubscribe</a>'
        expect(html.length).toBeLessThan(BODY_MAX_LENGTH)
        expect(preferencesTokensInBody({ html }, 'https://app.posthog.com')).toEqual(['tok-1'])
    })

    it('keeps the same first 50 tokens in document order with and without an SVG drawing', () => {
        const paragraphs = [
            '<p><a href="https://app.posthog.com/messaging-preferences/tok-first/">Unsubscribe</a></p>',
            ...Array.from(
                { length: UNSUBSCRIBE_TOKENS_CHECKED },
                (_, i) => `<p><a href="https://app.posthog.com/messaging-preferences/tok-other-${i}/">Other</a></p>`
            ),
        ].join('')
        const plain = preferencesTokensInBody({ html: paragraphs }, 'https://app.posthog.com')
        const withSvg = preferencesTokensInBody({ html: `<svg></svg>${paragraphs}` }, 'https://app.posthog.com')
        expect(plain).toContain('tok-first')
        expect(withSvg).toEqual(plain)
    })
})
