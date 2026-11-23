import { DefaultTreeAdapterMap, parse } from 'parse5'

import {
    BODY_MAX_LENGTH,
    UNSUBSCRIBE_TOKENS_CHECKED,
    clickableHrefs,
    hasReplaceableUnsubscribeLink,
    preferencesTokensInBody,
    replaceUnsubscribePlaceholder,
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
            'an anchor inside a script in an SVG foreignObject under a MathML annotation-xml element without an HTML encoding',
            '<math><annotation-xml><svg><foreignObject><script><a href="https://example.com/bye">Unsubscribe</a></script></foreignObject></svg></annotation-xml></math>',
            [],
        ],
        [
            'an SVG xlink:href anchor inside a MathML annotation-xml element without an HTML encoding',
            '<math><annotation-xml><svg><a xlink:href="https://example.com/bye"><text>Unsubscribe</text></a></svg></annotation-xml></math>',
            ['https://example.com/bye'],
        ],
        [
            'an SVG xlink:href anchor after an hr closes an open paragraph inside foreignObject',
            '<svg><foreignObject><p>News<hr></foreignObject><a xlink:href="https://example.com/bye"><text>Unsubscribe</text></a></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an SVG xlink:href anchor after an xmp block closes an open paragraph inside foreignObject',
            '<svg><foreignObject><p><xmp></xmp></foreignObject><a xlink:href="https://example.com/bye"><text>Unsubscribe</text></a></svg>',
            ['https://example.com/bye'],
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
        [
            'an anchor inside a textarea after closing a table whose MathML context was still open',
            '<table><math></table><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing a table cell whose MathML context was still open',
            '<table><td><math></td><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing a table around a cell whose MathML context was still open',
            '<table><td><math></table><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing a div whose MathML context was still open',
            '<div><math></div><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after an unmatched span end tag in MathML',
            '<div><math></span><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a textarea after closing a table while inside MathML mtext',
            '<table><math><mtext></table><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing a table cell across SVG foreignObject and nested MathML',
            '<table><td><svg><foreignObject><div><math></td><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an SVG textarea anchor after a paragraph end tag breaks out of nested SVG and closes the enclosing paragraph before closing foreignObject',
            '<svg><foreignObject><p><svg><rect></p></foreignObject><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            ['https://example.com/bye'],
        ],
        [
            'an HTML textarea anchor after a paragraph end tag breaks out of nested SVG and closes the enclosing paragraph before closing svg',
            '<svg><foreignObject><p><svg><rect></p></svg><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after an unmatched div end tag inside SVG foreignObject',
            '<div><svg><foreignObject></div><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after a div end tag blocked by a table cell scope barrier',
            '<div><table><td><math></div><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a textarea after closing a div whose nested SVG element was still open',
            '<div><svg><g></div><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after an SVG end tag closes its foreignObject ancestor',
            '<div><svg><g><foreignObject><div></div></g><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a textarea after closing body while SVG is still open',
            '<body><svg></body><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a textarea after closing a caption whose MathML context was still open',
            '<table><caption><math></caption><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing a table row whose MathML context was still open',
            '<table><tbody><tr><td><math></tr><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing a table section whose MathML context was still open',
            '<table><tbody><tr><td><math></tbody><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing an object barrier whose SVG context was still open',
            '<object><svg></object><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after closing an applet barrier whose SVG context was still open',
            '<applet><svg></applet><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
        ],
        [
            'an anchor inside a textarea after a div end tag blocked by an object scope barrier',
            '<div><object><svg></div><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor inside a textarea after closing an object barrier and then its enclosing div',
            '<div><object><svg></object></div><textarea><a href="https://example.com/bye">Unsubscribe</a></textarea>',
            [],
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

    it.each<[string, string]>([
        ['deeply nested markup', '<div>'.repeat(20_000)],
        ['an SVG drawing and a table with foster-parented elements', '<svg></svg><table>' + '<i></i>'.repeat(5_000)],
        [
            'an SVG drawing and repeated active formatting elements',
            '<svg></svg>' + '<div><table><object><b></table></div>'.repeat(10_000),
        ],
        [
            'a MathML annotation-xml element with a large encoding attribute followed by many tags',
            '<math><annotation-xml encoding="' + 'A'.repeat(100_000) + '">' + '<x></x>'.repeat(20_000) + '</math>',
        ],
        [
            'an SVG element with a large tag name followed by many end tags',
            '<svg><' + 'a'.repeat(100_000) + '>' + '</x>'.repeat(20_000) + '</svg>',
        ],
        [
            'deeply nested SVG elements followed by unmatched end tags',
            '<svg>' + '<g>'.repeat(20_000) + '</x>'.repeat(20_000) + '</svg>',
        ],
        [
            'many nested MathML text integration points followed by unmatched SVG end tags',
            '<math><mtext>'.repeat(20_000) + '</svg>'.repeat(20_000),
        ],
    ])('finds the anchor after large %s', (_name, filler) => {
        expect(clickableHrefs(filler + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([
            'https://example.com/bye',
        ])
    })

    it('matches parse5 document parsing across combinations of tables, divs, selects, templates, and foreign content', () => {
        const parse5Hrefs = (html: string): string[] => {
            const doc = parse(html)
            const hrefs = new Set<string>()
            const stack: DefaultTreeAdapterMap['parentNode'][] = [doc]
            for (let node = stack.pop(); node; node = stack.pop()) {
                if ('tagName' in node && node.tagName === 'a') {
                    const href =
                        node.attrs.find(({ name, namespace }) => name === 'href' && !namespace) ??
                        (node.namespaceURI === 'http://www.w3.org/2000/svg'
                            ? node.attrs.find(({ name }) => name === 'href')
                            : undefined)
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
            '<div>',
            '</div>',
            '<span>',
            '</span>',
            '<table>',
            '<table><tr><td>',
            '<table><caption>',
            '<table><tbody><tr><td>',
            '<thead>',
            '</thead>',
            '<th>',
            '</th>',
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
            '<g>',
            '</g>',
            '<svg><title>',
            '</title>',
            '<svg><foreignObject>',
            '</foreignObject>',
            '<svg><style>',
            '</style>',
            '<math>',
            '<math><mtext>',
            '</mtext>',
            '<annotation-xml>',
            '<annotation-xml encoding="text/html">',
            '</annotation-xml>',
            '<object>',
            '</object>',
            '<foreignObject>',
            '</math>',
            '<p>',
            '</p>',
            '<hr>',
            '</br>',
            '<script>',
            '</script>',
            '<style>',
            '<noscript>',
            '</noscript>',
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
        for (let i = 0; i < 1_000; i++) {
            const length = 2 + nextInt(7)
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
    it('extracts the preferences token alongside long Unicode and oversized hostnames', () => {
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

    it('extracts the preferences token from an SVG xlink:href anchor after hr closes a paragraph in foreignObject', () => {
        const html =
            '<svg><foreignObject><p>News<hr></foreignObject><a xlink:href="{{ unsubscribe_url }}"><text>Unsubscribe</text></a></svg>'
        expect(hasReplaceableUnsubscribeLink({ html })).toBe(true)
        const filled = replaceUnsubscribePlaceholder(html, 'https://app.posthog.com/messaging-preferences/tok-hr/')
        expect(preferencesTokensInBody({ html: filled }, 'https://app.posthog.com')).toEqual(['tok-hr'])
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
    ])('finds the replaceable link alongside 80,000 %s', (_name, markers) => {
        const html = `<!-- ${markers} --><a href="{{ unsubscribe_url }}">Unsubscribe</a>`
        expect(html.length).toBeLessThan(BODY_MAX_LENGTH)
        expect(hasReplaceableUnsubscribeLink({ html })).toBe(true)
    })
})
