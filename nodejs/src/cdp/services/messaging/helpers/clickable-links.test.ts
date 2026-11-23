import { DefaultTreeAdapterMap, parse } from 'parse5'

import {
    BODY_MAX_LENGTH,
    UNSUBSCRIBE_TOKENS_CHECKED,
    clickableHrefs,
    hasReplaceableUnsubscribeLink,
    preferencesTokensInBody,
} from './clickable-links'

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
            'an anchor inside a script after a paragraph end tag breaks out of an SVG drawing',
            '<svg></p><script><a href="https://example.com/bye">Unsubscribe</a></script></svg>',
            [],
        ],
        [
            'an anchor inside a script after a line-break end tag breaks out of an SVG drawing',
            '<svg></br><script><a href="https://example.com/bye">Unsubscribe</a></script></svg>',
            [],
        ],
        [
            'an anchor with only xlink:href after a paragraph end tag breaks out of an SVG drawing',
            '<svg></p><a xlink:href="https://example.com/bye">Unsubscribe</a></svg>',
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
            'an anchor after an unclosed select closed by its closing table tag',
            '<table><tr><td><select></table><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an unclosed select closed by its closing table cell tag',
            '<table><tr><td><select></td><a href="https://example.com/bye">Unsubscribe</a></tr></table>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an unclosed select closed by its closing table row tag',
            '<table><tr><td><select></tr><a href="https://example.com/bye">Unsubscribe</a></table>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an unclosed select closed by a table row start tag',
            '<table><select><tr><td><a href="https://example.com/bye">Unsubscribe</a></td></tr></table>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an unclosed select closed by a caption start tag',
            '<table><select><caption><a href="https://example.com/bye">Unsubscribe</a></caption></table>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an unclosed select closed by a nested table start tag',
            '<table><select><table><tr><td><a href="https://example.com/bye">Unsubscribe</a></td></tr></table>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after a closing cell tag that was not open around a select in a table',
            '<table><select></td><a href="https://example.com/bye">Unsubscribe</a></table>',
            [],
        ],
        [
            'an anchor after a stray closing table tag inside a select outside a table',
            '<select></table><a href="https://example.com/bye">Unsubscribe</a>',
            [],
        ],
        [
            'an anchor inside a select in a table when a template closes a cell inside it',
            '<table><tr><td><select><template></td></template><a href="https://example.com/bye">Unsubscribe</a></select></td></tr></table>',
            [],
        ],
        [
            'an anchor after a template with an unclosed select',
            '<template><select></template><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a bogus CDATA comment after a template with an unclosed SVG element',
            '<template><svg></template><![CDATA[><a href="https://example.com/bye">Unsubscribe</a>]]>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a style block after a template with an unclosed SVG element',
            '<template><svg></template><style><a href="https://example.com/bye">Unsubscribe</a></style>',
            [],
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

    it.each<[string, (n: number) => string, number, number]>([
        ['deeply nested markup', (n) => '<div>'.repeat(n), 2_000, 20_000],
        [
            'an SVG drawing and a table with foster-parented elements',
            (n) => '<svg></svg><table>' + '<i></i>'.repeat(n),
            500,
            5_000,
        ],
        [
            'an SVG drawing and repeated active formatting elements',
            (n) => '<svg></svg>' + '<div><table><object><b></table></div>'.repeat(n),
            1_000,
            10_000,
        ],
        [
            'a MathML annotation-xml element with a large encoding attribute followed by many tags',
            (n) => '<math><annotation-xml encoding="' + 'A'.repeat(n * 5) + '">' + '<x></x>'.repeat(n) + '</math>',
            2_000,
            20_000,
        ],
        [
            'an SVG element with a large tag name followed by many end tags',
            (n) => '<svg><' + 'a'.repeat(n * 5) + '>' + '</x>'.repeat(n) + '</svg>',
            2_000,
            20_000,
        ],
        [
            'many nested MathML text integration points followed by unmatched SVG end tags',
            (n) => '<math><mtext>'.repeat(n) + '</svg>'.repeat(n),
            2_000,
            20_000,
        ],
    ])('finds the anchor with linearly bounded work after %s', (_name, buildFiller, smallN, largeN) => {
        const smallStats = { tokens: 0, contextOps: 0 }
        const largeStats = { tokens: 0, contextOps: 0 }
        expect(
            clickableHrefs(buildFiller(smallN) + '<a href="https://example.com/bye">Unsubscribe</a>', smallStats)
        ).toEqual(['https://example.com/bye'])
        expect(
            clickableHrefs(buildFiller(largeN) + '<a href="https://example.com/bye">Unsubscribe</a>', largeStats)
        ).toEqual(['https://example.com/bye'])
        expect(largeStats.tokens).toBeLessThanOrEqual(smallStats.tokens * 12)
        expect(largeStats.contextOps).toBeLessThanOrEqual(Math.max(smallStats.contextOps * 12, 20))
    })
    it('matches parse5 document parsing across well-scoped combinations of tables, selects, templates, and foreign content', () => {
        const parse5Hrefs = (html: string): string[] => {
            const doc = parse(html)
            const hrefs = new Set<string>()
            const stack: DefaultTreeAdapterMap['parentNode'][] = [doc]
            for (let node = stack.pop(); node; node = stack.pop()) {
                if ('tagName' in node && node.tagName === 'a') {
                    const href =
                        node.attrs.find(({ name, namespace }) => name === 'href' && !namespace) ??
                        node.attrs.find(({ name }) => name === 'href')
                    if (href) {
                        hrefs.add(href.value)
                    }
                }
                for (let i = node.childNodes.length - 1; i >= 0; i--) {
                    const child = node.childNodes[i]
                    if ('tagName' in child) {
                        stack.push(child)
                    }
                }
            }
            return [...hrefs]
        }

        const fragments = [
            '<table><tr><td>',
            '<table><caption>',
            '<table><tbody><tr><td>',
            '<select>',
            '</select>',
            '<input>',
            '<textarea>',
            '</textarea>',
            '</td>',
            '</tr>',
            '</tbody>',
            '</caption>',
            '</table>',
            '<template>',
            '</template>',
            '<svg>',
            '</svg>',
            '<svg><title>',
            '</title>',
            '<svg><foreignObject>',
            '</foreignObject>',
            '<svg><style>',
            '</style>',
            '<math><mtext>',
            '</mtext>',
            '</math>',
            '<p>',
            '</p>',
            '</br>',
            '<script>',
            '</script>',
            '<style>',
            '<![CDATA[><a href="https://example.com/cdata">c</a>]]>',
            '<!-- <a href="https://example.com/comment">m</a> -->',
            '<a href="https://example.com/bye">Unsubscribe</a>',
            '<a xlink:href="https://example.com/svg">SVG</a>',
        ]
        let seed = 0x51a7c0de
        const nextInt = (max: number): number => {
            seed = (seed * 1664525 + 1013904223) >>> 0
            return seed % max
        }
        const mismatches: Array<{ html: string; actual: string[]; expected: string[] }> = []
        for (let i = 0; i < 600; i++) {
            const length = 2 + nextInt(6)
            let html = ''
            for (let j = 0; j < length; j++) {
                html += fragments[nextInt(fragments.length)]
            }
            html += '<a href="https://example.com/tail">Unsubscribe</a>'
            const actual = [...clickableHrefs(html)].sort()
            const expected = [...parse5Hrefs(html)].sort()
            if (JSON.stringify(actual) !== JSON.stringify(expected)) {
                mismatches.push({ html, actual, expected })
                if (mismatches.length >= 5) {
                    break
                }
            }
        }
        expect(mismatches).toEqual([])
    })
})

describe('preferencesTokensInBody', () => {
    it('extracts the preferences token without IDNA-normalizing long Unicode hostnames', () => {
        const unicodeHost = Array.from({ length: 4_000 }, (_, i) => String.fromCodePoint(0x4e00 + i)).join('')
        const unicodeLinks = Array.from({ length: 160 }, (_, i) => `<a href="https://${unicodeHost}/p${i}">x</a>`).join(
            ''
        )
        const specialSchemeLinks = [
            `<a href="https://bücher.example/p">x</a>`,
            `<a href="https://${'a'.repeat(300)}.example/p">x</a>`,
            `<a href="https:\\\\${unicodeHost}/p">x</a>`,
            `<a href="https://\t/${unicodeHost}/p">x</a>`,
            `<a href="https:${unicodeHost}/p">x</a>`,
        ].join('')
        const html =
            unicodeLinks +
            specialSchemeLinks +
            '<a href="https://app.posthog.com/messaging-preferences/tok-1/">Unsubscribe</a>'
        expect(html.length).toBeLessThan(BODY_MAX_LENGTH)
        const stats = { urlParses: 0 }
        expect(preferencesTokensInBody({ html }, 'https://app.posthog.com', stats)).toEqual(['tok-1'])
        expect(stats.urlParses).toBe(1)
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

describe('hasReplaceableUnsubscribeLink', () => {
    it.each([
        {
            name: 'a plain placeholder href',
            content: { html: '<a href="{{ unsubscribe_url }}">Unsubscribe</a>' },
            expected: true,
        },
        {
            name: 'a placeholder href surrounded by spaces',
            content: { html: '<a href="  {{ unsubscribe_url }}  ">Unsubscribe</a>' },
            expected: true,
        },
        {
            name: 'a placeholder href with a query string',
            content: { html: '<a href="{{ unsubscribe_url }}?utm_source=x">Unsubscribe</a>' },
            expected: true,
        },
        {
            name: 'a placeholder padded to the size limit',
            content: { html: '<a href="{{ unsubscribe_url }}">Unsubscribe</a>'.padEnd(BODY_MAX_LENGTH, 'x') },
            expected: true,
        },
        {
            name: 'a placeholder with HTML entities inside the braces',
            content: { html: '<a href="{{&#32;unsubscribe_url&#32;}}">Unsubscribe</a>' },
            expected: false,
        },
        {
            name: 'a placeholder wrapped in another host URL',
            content: { html: '<a href="https://example.com/?next={{ unsubscribe_url }}">Unsubscribe</a>' },
            expected: false,
        },
        {
            name: 'a placeholder followed by extra path text',
            content: { html: '<a href="{{ unsubscribe_url }}extra">Unsubscribe</a>' },
            expected: false,
        },
        {
            name: 'a body that already contains the first sentinel URL outside a placeholder',
            content: { html: '<a href="https://a/_0/">Fake</a><!-- {{ unsubscribe_url }} -->' },
            expected: false,
        },
        {
            name: 'a body that entity-encodes a deterministic sentinel URL outside a placeholder',
            content: { html: '<a href="https://a/&#95;0/">Fake</a><!-- {{ unsubscribe_url }} -->' },
            expected: false,
        },
        {
            name: 'a body that entity-encodes a padded sentinel URL outside a placeholder',
            content: { html: '<a href="https://a/&#95;00000/">Fake</a><!-- {{ unsubscribe_url }} -->' },
            expected: false,
        },
        {
            name: 'a text-only body with the placeholder',
            content: { text: 'Unsubscribe: {{ unsubscribe_url }}' },
            expected: true,
        },
        {
            name: 'a text-only body without the placeholder',
            content: { text: 'Unsubscribe here' },
            expected: false,
        },
    ])('returns $expected for $name', ({ content, expected }) => {
        expect(hasReplaceableUnsubscribeLink(content)).toBe(expected)
    })

    it.each([
        ['short sequential base-36 markers', Array.from({ length: 80_000 }, (_, i) => `_${i.toString(36)}`).join(' ')],
        [
            'fixed-width base-36 markers',
            Array.from({ length: 80_000 }, (_, i) => `_${i.toString(36).padStart(5, '0')}`).join(' '),
        ],
    ])('selects an unused sentinel in linear time with 80,000 %s', (_name, markers) => {
        const html = `<!-- ${markers} --><a href="{{ unsubscribe_url }}">Unsubscribe</a>`
        expect(html.length).toBeLessThan(BODY_MAX_LENGTH)
        const stats = { sentinelScans: 0, tokens: 0, contextOps: 0 }
        expect(hasReplaceableUnsubscribeLink({ html }, stats)).toBe(true)
        expect(stats.sentinelScans).toBeLessThanOrEqual(5)
    })
})
