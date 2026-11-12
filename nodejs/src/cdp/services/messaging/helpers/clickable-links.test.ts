import { clickableHrefs } from './clickable-links'

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
            [],
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
            'an anchor inside the title of an SVG drawing',
            '<svg><title><a href="https://example.com/bye">Unsubscribe</a></title></svg>',
            [],
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
            'an anchor before an SVG drawing',
            '<a href="https://example.com/bye">Unsubscribe</a><svg><circle r="1"></circle></svg>',
            ['https://example.com/bye'],
        ],
        [
            'an anchor after an SVG drawing',
            '<svg><circle r="1"></circle></svg><a href="https://example.com/bye">Unsubscribe</a>',
            [],
        ],
        [
            'an anchor in CDATA after a nested SVG drawing',
            '<svg><svg></svg><![CDATA[> <a href="https://example.com/bye">Unsubscribe</a>]]></svg>',
            [],
        ],
        [
            'an anchor in CDATA inside a MathML element name in an SVG drawing',
            '<svg><mtext><![CDATA[> <a href="https://example.com/bye">Unsubscribe</a>]]></mtext></svg>',
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
            'an anchor inside a script that a select hides from the raw text start tag before it',
            '<select><xmp></select><script></xmp></select><a href="https://example.com/bye">Unsubscribe</a></script>',
            [],
        ],
        [
            'an anchor inside a script that a template column group hides from the raw text start tag before it',
            '<template><col><xmp></template><script></xmp></template><a href="https://example.com/bye">Unsubscribe</a></script>',
            [],
        ],
        [
            'an anchor inside a self-closing template',
            '<template/><a href="https://example.com/bye">Unsubscribe</a>',
            [],
        ],
        [
            'an anchor in a body a frameset replaces',
            '<a href="https://example.com/bye">Unsubscribe</a><frameset></frameset>',
            [],
        ],
    ])('returns the hrefs a reader can click in %s', (_name, html, hrefs) => {
        expect(clickableHrefs(html)).toEqual(hrefs)
    })

    it('finds the anchor after deeply nested markup', () => {
        expect(clickableHrefs('<div>'.repeat(40_000) + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([
            'https://example.com/bye',
        ])
    })
})
