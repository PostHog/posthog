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
        [
            'an anchor after an Outlook conditional comment containing noscript',
            '<!--[if mso]><noscript><xml><o:OfficeDocumentSettings></o:OfficeDocumentSettings></xml></noscript><![endif]--><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor before a frameset inside an HTML comment',
            '<a href="https://example.com/bye">Unsubscribe</a><!-- <frameset> -->',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after a style block mentioning svg',
            '<style>/* <svg></svg> <a href="https://example.com/fake">Fake</a> */</style><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after a script block mentioning select',
            '<script>const x = "<select><a href=\\"https://example.com/fake\\">Fake</a></select>"</script><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        ['an anchor inside an HTML comment', '<!-- <a href="https://example.com/bye">Unsubscribe</a> -->', []],
        ['the address in another attribute of an anchor', '<a title="https://example.com/bye">Unsubscribe</a>', []],
        ['an anchor with only xlink:href', '<a xlink:href="https://example.com/bye">Unsubscribe</a>', []],
        ['the address on an element that is not an anchor', '<link href="https://example.com/bye">', []],
        ['the address as text', '<p>https://example.com/bye</p>', []],
        [
            'an anchor with an encoded ampersand',
            '<a href="https://example.com/bye?a=1&amp;b=2">Unsubscribe</a>',
            ['https://example.com/bye?a=1&b=2'],
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
        ['an anchor inside xmp', '<xmp><a href="https://example.com/bye">Unsubscribe</a></xmp>', []],
        ['an anchor inside an iframe', '<iframe><a href="https://example.com/bye">Unsubscribe</a></iframe>', []],
        ['an anchor inside noembed', '<noembed><a href="https://example.com/bye">Unsubscribe</a></noembed>', []],
        ['an anchor inside noframes', '<noframes><a href="https://example.com/bye">Unsubscribe</a></noframes>', []],
        ['an anchor after plaintext', '<plaintext><a href="https://example.com/bye">Unsubscribe</a>', []],
        ['an anchor after a self-closing style tag', '<style/><a href="https://example.com/bye">Unsubscribe</a>', []],
        [
            'an anchor after an element named like an object property',
            '<constructor></constructor><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after a closed script',
            '<script>let a = 1</script><a href="https://example.com/bye">Unsubscribe</a>',
            ['https://example.com/bye'],
        ],
    ])('returns the hrefs a reader can click in %s', (_name, html, hrefs) => {
        expect(clickableHrefs(html)).toEqual(hrefs)
    })

    it.each([
        ['frameset', '<frameset><a href="https://example.com/bye">Unsubscribe</a></frameset>'],
        ['template', '<template></template><a href="https://example.com/bye">Unsubscribe</a>'],
        ['select', '<select></select><a href="https://example.com/bye">Unsubscribe</a>'],
        ['svg', '<svg></svg><a href="https://example.com/bye">Unsubscribe</a>'],
        ['math', '<math></math><a href="https://example.com/bye">Unsubscribe</a>'],
        ['noscript', '<noscript></noscript><a href="https://example.com/bye">Unsubscribe</a>'],
        ['an anchor before a forbidden svg tag', '<a href="https://example.com/bye">Unsubscribe</a><svg></svg>'],
        ['a stray closing template tag', '</template><a href="https://example.com/bye">Unsubscribe</a>'],
        [
            'B3: a table and select inside a frameset',
            '<frameset><table><select></table><a href="https://example.com/bye">Unsubscribe</a></frameset>',
        ],
        [
            'M1: a misplaced span end tag inside svg',
            '<span><div><svg></span><a xlink:href="https://example.com/bye"><text>Unsubscribe</text></a></svg></div>',
        ],
    ])('fails closed on markup containing %s', (_name, html) => {
        expect(clickableHrefs(html)).toEqual([])
    })

    it.each([
        ['longer than the tokenizer reads', ' '.repeat(BODY_MAX_LENGTH)],
        ['with more attributes on one tag than the tokenizer reads', `<div ${manyAttributes}></div>`],
    ])('fails closed on markup %s', (_name, filler) => {
        const html = filler + '<a href="https://example.com/bye">Unsubscribe</a>'
        expect(clickableHrefs(html)).toEqual([])
    })

    it.each<[string, string]>([
        ['deeply nested markup', '<div>'.repeat(20_000)],
        ['a table with many formatting elements', '<table>' + '<i></i>'.repeat(5_000) + '</table>'],
        [
            'deeply nested divs followed by repeated form end tags',
            '<div>'.repeat(20_000) + '<form></form>'.repeat(5_000),
        ],
    ])('finds the anchor after large %s', (_name, filler) => {
        expect(clickableHrefs(filler + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([
            'https://example.com/bye',
        ])
    })

    it('never accepts a body where parse5 finds no anchor with the placeholder', () => {
        const sentinelUrl = 'https://app.posthog.com/messaging-preferences/tok-check/'
        const parse5HasAnchor = (html: string, targetHref: string): boolean => {
            const doc = parse(html)
            const stack: DefaultTreeAdapterMap['parentNode'][] = [doc]
            for (let node = stack.pop(); node; node = stack.pop()) {
                if ('tagName' in node && node.tagName === 'a') {
                    const href = node.attrs.find(({ name, namespace }) => name === 'href' && !namespace)
                    if (href && href.value.trim() === targetHref) {
                        return true
                    }
                }
                for (let i = node.childNodes.length - 1; i >= 0; i--) {
                    const child = node.childNodes[i]
                    if ('tagName' in child) {
                        stack.push(child)
                    }
                }
            }
            return false
        }

        const refusedCases = [
            '<frameset><table><select></table><a href="{{ unsubscribe_url }}">Unsubscribe</a></frameset>',
            '<span><div><svg></span><a xlink:href="{{ unsubscribe_url }}"><text>Unsubscribe</text></a></svg></div>',
            '<template><a href="{{ unsubscribe_url }}">Unsubscribe</a></template>',
            '<select><option><a href="{{ unsubscribe_url }}">Unsubscribe</a></option></select>',
            '<math><mtext><a href="{{ unsubscribe_url }}">Unsubscribe</a></mtext></math>',
            '<noscript><a href="{{ unsubscribe_url }}">Unsubscribe</a></noscript>',
        ]
        for (const html of refusedCases) {
            expect(hasReplaceableUnsubscribeLink({ html })).toBe(false)
        }

        const fragments = [
            '<html>',
            '</html>',
            '<head>',
            '</head>',
            '<body>',
            '</body>',
            '<div>',
            '</div>',
            '<span>',
            '</span>',
            '<b>',
            '</b>',
            '<table>',
            '<table><tr><td>',
            '<table><caption>',
            '<table><tbody><tr><td>',
            '<colgroup>',
            '</colgroup>',
            '<col>',
            '<caption>',
            '<tbody>',
            '<tfoot>',
            '<tr>',
            '<td>',
            '<thead>',
            '</thead>',
            '<th>',
            '</th>',
            '</td>',
            '</tr>',
            '</tbody>',
            '</caption>',
            '</table>',
            '<frameset>',
            '</frameset>',
            '<select>',
            '</select>',
            '<input>',
            '<textarea>',
            '</textarea>',
            '<title>',
            '</title>',
            '<template>',
            '</template>',
            '<svg>',
            '</svg>',
            '<math>',
            '</math>',
            '<noscript>',
            '</noscript>',
            '<object>',
            '</object>',
            '<p>',
            '</p>',
            '<form>',
            '</form>',
            '<hr>',
            '</br>',
            '<script>',
            '</script>',
            '<style>',
            '</style>',
            '<xmp>',
            '</xmp>',
            '<iframe>',
            '</iframe>',
            '<noembed>',
            '</noembed>',
            '<noframes>',
            '</noframes>',
            '<plaintext>',
            '<![CDATA[><a href="{{ unsubscribe_url }}">c</a>]]>',
            '<!-- <a href="{{ unsubscribe_url }}">m</a> -->',
            '<!--[if mso]><noscript><xml></xml></noscript><![endif]-->',
            '<a href="{{ unsubscribe_url }}">Unsubscribe</a>',
            '<a xlink:href="{{ unsubscribe_url }}">SVG</a>',
        ]
        let seed = 0x51a7c0de
        const nextInt = (max: number): number => {
            seed = (seed * 1664525 + 1013904223) >>> 0
            return seed % max
        }
        const falseAccepts: string[] = []
        for (let i = 0; i < 2_000; i++) {
            const length = 2 + nextInt(7)
            let html = ''
            for (let j = 0; j < length; j++) {
                html += fragments[nextInt(fragments.length)]
            }
            html += '<a href="{{ unsubscribe_url }}">Unsubscribe</a>'
            if (hasReplaceableUnsubscribeLink({ html })) {
                const filled = replaceUnsubscribePlaceholder(html, sentinelUrl)
                if (!parse5HasAnchor(filled, sentinelUrl)) {
                    falseAccepts.push(html)
                    if (falseAccepts.length >= 5) {
                        break
                    }
                }
            }
        }
        expect(falseAccepts).toEqual([])
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

    it('keeps the first 50 distinct tokens in document order', () => {
        const paragraphs = [
            '<p><a href="https://app.posthog.com/messaging-preferences/tok-first/">Unsubscribe</a></p>',
            ...Array.from(
                { length: UNSUBSCRIBE_TOKENS_CHECKED },
                (_, i) => `<p><a href="https://app.posthog.com/messaging-preferences/tok-other-${i}/">Other</a></p>`
            ),
        ].join('')
        const tokens = preferencesTokensInBody({ html: paragraphs }, 'https://app.posthog.com')
        expect(tokens).toHaveLength(UNSUBSCRIBE_TOKENS_CHECKED)
        expect(tokens[0]).toBe('tok-first')
    })

    it('extracts the token from a rendered one-click unsubscribe link with an ampersand parameter', () => {
        const html =
            '<a href="https://app.posthog.com/messaging-preferences/tok-1/?one_click_unsubscribe=1&amp;lang=de">Unsubscribe</a>'
        expect(preferencesTokensInBody({ html }, 'https://app.posthog.com')).toEqual(['tok-1'])
    })

    it('returns no tokens when a forbidden tag appears alongside a valid preferences link', () => {
        const html = '<svg></svg><a href="https://app.posthog.com/messaging-preferences/tok-1/">Unsubscribe</a>'
        expect(preferencesTokensInBody({ html }, 'https://app.posthog.com')).toEqual([])
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
            name: 'a placeholder after an Outlook conditional comment with noscript',
            content: {
                html: '<!--[if mso]><noscript><xml></xml></noscript><![endif]--><a href="{{ unsubscribe_url }}">Unsubscribe</a>',
            },
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
            name: 'B3: a frameset containing a table and select before the unsubscribe link',
            content: {
                html: '<frameset><table><select></table><a href="{{ unsubscribe_url }}">Unsubscribe</a></frameset>',
            },
            expected: false,
        },
        {
            name: 'M1: an svg anchor after a misplaced span end tag',
            content: {
                html: '<span><div><svg></span><a xlink:href="{{ unsubscribe_url }}"><text>Unsubscribe</text></a></svg></div>',
            },
            expected: false,
        },
        {
            name: 'a forbidden tag with no placeholder at all',
            content: { html: '<svg></svg><p>News</p>' },
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
})
