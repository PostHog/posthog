import type { RepositoryFileApi } from 'products/business_knowledge/frontend/generated/api.schemas'

import { codeExcerptCandidates, codeIdentifiers, findCodeQuote } from './todayQuotedCode'

function read(path: string, lines: string[]): RepositoryFileApi {
    return { content: lines.join('\n'), url: `https://github.com/example/shop/blob/abc/${path}` } as RepositoryFileApi
}

const OWN = { repo: 'example/shop', path: 'src/cards/Cards.tsx' }
const SIBLING = { repo: 'example/shop', path: 'src/cards/cardsLogic.ts' }
const OWN_READ = read(OWN.path, ['export function Cards(): JSX.Element {', '    return <List />', '}'])
const SIBLING_READ = read(SIBLING.path, ['const PAGE_SIZE = 50', 'export const CARDS_MAX = 120'])

describe('todayQuotedCode', () => {
    test('keeps member expressions and drops file names and blank spans', () => {
        expect(codeIdentifiers('`response.json` and `Math.max` in `Cards.tsx`, then `   `.')).toEqual([
            'response.json',
            'Math.max',
        ])
    })

    test('picks the lines a finding quotes and marks the quoted code', () => {
        const file = [
            "import { useValues } from 'kea'",
            '',
            'export function CartRow({ productId }: Props): JSX.Element {',
            '    const { prices } = useValues(pricesLogic)',
            '    const price = prices[productId]',
            '    return <Price price={price} />',
            '}',
        ].join('\n')
        const identifiers = codeIdentifiers(
            '`CartRow.tsx` calls `useValues` on the store-wide logic and reads `prices[productId]` afterward.'
        )
        expect(identifiers).toEqual(['useValues', 'prices[productId]'])
        expect(codeExcerptCandidates(file, identifiers)[0]).toEqual({
            startLine: 3,
            lines: [
                'export function CartRow({ productId }: Props): JSX.Element {',
                '    const { prices } = useValues(pricesLogic)',
                '    const price = prices[productId]',
                '    return <Price price={price} />',
                '}',
            ],
            marks: [
                { line: 1, start: 23, end: 32 },
                { line: 2, start: 18, end: 35 },
            ],
        })
    })

    test('marks every quoted name on a line in reading order, whatever order the finding names them in', () => {
        const [excerpt] = codeExcerptCandidates('total = helper(compute_total())', ['compute_total', 'helper'])
        expect(excerpt.marks).toEqual([
            { line: 0, start: 8, end: 14 },
            { line: 0, start: 15, end: 28 },
        ])
    })

    test('shows the lines that hold the most distinct pieces of the quoted code', () => {
        const gap = Array(9).fill('')
        const file = [
            'const a = rareName',
            ...gap,
            'one(commonName, otherName)',
            ...gap,
            'two(commonName)',
            ...gap,
            'three(otherName)',
        ].join('\n')
        expect(codeExcerptCandidates(file, ['rareName', 'commonName', 'otherName'])[0]?.startLine).toEqual(11)
    })

    test('offers each separate place that holds most of the quoted code', () => {
        const file = [
            'actions({',
            '    addItem: (id: string) => ({ id }),',
            '    removeItem: (id: string) => ({ id }),',
            '}),',
            ...Array(6).fill(''),
            'reducers({',
            '    items: [',
            '        {},',
            '        {',
            '            addItem: (state, { id }) => ({ ...state, [id]: true }),',
            '            removeItem: (state, { id }) => ({ ...state, [id]: false }),',
        ].join('\n')
        expect(
            codeExcerptCandidates(file, ['items', 'addItem', 'removeItem']).map((excerpt) => excerpt.startLine)
        ).toEqual([11, 1])
    })

    test.each([
        ['the sibling file that holds the quote', [OWN_READ, SIBLING_READ], 'cardsLogic.ts'],
        ['nothing when no file holds the quote', [OWN_READ, null], null],
    ])('chooses %s', (_, reads, expected) => {
        const chosen = findCodeQuote([OWN, SIBLING], reads, ['CARDS_MAX = 120'])
        expect(chosen?.file.path.split('/').pop() ?? null).toEqual(expected)
    })
})
