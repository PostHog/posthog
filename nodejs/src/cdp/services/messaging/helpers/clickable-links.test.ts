import { TREE_MAX_DEPTH, TREE_MAX_ELEMENTS, TREE_MAX_LENGTH, TREE_MAX_SCANS, clickableHrefs } from './clickable-links'

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
            'an anchor inside the title of an SVG drawing',
            '<svg><title><a href="https://example.com/bye">Unsubscribe</a></title></svg>',
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
            'an anchor before an SVG drawing',
            '<a href="https://example.com/bye">Unsubscribe</a><svg><circle r="1"></circle></svg>',
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
            'an anchor before a frameset inside a comment',
            '<a href="https://example.com/bye">Unsubscribe</a><!-- <frameset> -->',
            ['https://example.com/bye'],
        ],
        [
            'an empty anchor in a body a frameset replaces',
            '<a href="https://example.com/bye"></a><frameset></frameset>',
            [],
        ],
    ])('returns the hrefs a reader can click in %s', (_name, html, hrefs) => {
        expect(clickableHrefs(html)).toEqual(hrefs)
    })

    it.each([
        ['nested deeper than the parser follows', '<div>'.repeat(TREE_MAX_DEPTH)],
        ['longer than the parser reads', ' '.repeat(TREE_MAX_LENGTH)],
        ['with more attributes on one tag than the parser reads', `<div ${manyAttributes}></div>`],
        [
            'that rebuilds more elements than the parser keeps',
            '<div>' +
                Array.from({ length: 100 }, (_, index) => `<b id="${index}">`).join('') +
                '</div>' +
                '<div>x</div>'.repeat(TREE_MAX_ELEMENTS / 100),
        ],
        [
            'that moves more elements out of a table than the parser scans past',
            '<table>' + '<i></i>'.repeat(Math.ceil(Math.sqrt(2 * TREE_MAX_SCANS))),
        ],
        [
            'that moves more text out of a table than the parser scans past',
            '<table>' + 'x<br>'.repeat(Math.ceil(Math.sqrt(TREE_MAX_SCANS / 2))),
        ],
        [
            'that moves more elements out of a misnested tag than the parser scans past',
            '<b><div>' + '<i></i>'.repeat(Math.ceil(Math.sqrt(2 * TREE_MAX_SCANS))) + '</b>',
        ],
        [
            'that adds more attributes to the root element than the parser scans past',
            Array.from(
                { length: Math.ceil(Math.sqrt(TREE_MAX_SCANS / 8)) },
                (_, tag) => `<html ${Array.from({ length: 16 }, (_, attribute) => `a${tag}x${attribute}`).join(' ')}>`
            ).join(''),
        ],
    ])('finds no anchor after an SVG drawing in markup %s', (_name, filler) => {
        expect(clickableHrefs('<svg></svg>' + filler + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([])
    })

    it.each([
        ['deeply nested markup', '<div>'.repeat(40_000)],
        ['an SVG drawing and a table it moves elements out of', '<svg></svg><table>' + '<i></i>'.repeat(1_000)],
    ])('finds the anchor after %s', (_name, filler) => {
        expect(clickableHrefs(filler + '<a href="https://example.com/bye">Unsubscribe</a>')).toEqual([
            'https://example.com/bye',
        ])
    })

    it('finds no anchor after a tag with more attributes than the scanner reads', () => {
        expect(
            clickableHrefs(`<div ${manyAttributes}></div><a href="https://example.com/bye">Unsubscribe</a>`)
        ).toEqual([])
    })
})
