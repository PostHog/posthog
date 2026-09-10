import { formatPreviewCell } from './previewCell'

describe('formatPreviewCell', () => {
    it.each<[string, unknown, string]>([
        ['a string', 'orders', 'orders'],
        ['a number', 42, '42'],
        ['a boolean', false, 'false'],
        ['null as empty', null, ''],
        ['undefined as empty', undefined, ''],
        ['an array', [1, 2], '[1,2]'],
        ['an object', { id: 7 }, '{"id":7}'],
        // A raw object like this would otherwise reach LemonTable and inject markup via its props.
        [
            'a cell-representation shape',
            { props: { dangerouslySetInnerHTML: { __html: '<img src=x onerror=alert(1)>' } } },
            '{"props":{"dangerouslySetInnerHTML":{"__html":"<img src=x onerror=alert(1)>"}}}',
        ],
    ])('renders %s as text', (_case, value, expected) => {
        expect(formatPreviewCell(value)).toEqual(expected)
    })
})
