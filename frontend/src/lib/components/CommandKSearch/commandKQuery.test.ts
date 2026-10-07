import {
    FilterKey,
    QueryChip,
    ValueOption,
    FilterOptions,
    chipCommittedByEdit,
    extractChips,
    getCursorContext,
    isRedundantSpace,
    matchValueOptions,
    queryAsText,
    removeToken,
    resolveQuery,
    tokenize,
    unambiguousOption,
} from './commandKQuery'

const TYPE_OPTIONS: ValueOption[] = [
    { value: 'dashboard', label: 'Dashboard' },
    { value: 'early_access_feature', label: 'Early access feature' },
    { value: 'feature_flag', label: 'Feature flag', aliases: ['flag'] },
    { value: 'insight', label: 'Insight' },
]
const USER_OPTIONS: ValueOption[] = [
    { value: 'me', label: 'Me' },
    { value: 'mel@example.com', label: 'Mel Ortiz', aliases: ['Mel', 'Ortiz', 'mel@example.com'] },
    { value: 'carla@example.com', label: 'Carla Diaz', aliases: ['Carla', 'Diaz', 'carla@example.com'] },
]
const OPTIONS: FilterOptions = { is: TYPE_OPTIONS, createdBy: USER_OPTIONS, in: [], name: [] }

const chip = (key: FilterKey, value: string, negated = false): QueryChip => ({ key, value, label: value, negated })

describe('commandKQuery', () => {
    test('keeps quoted values with spaces as one token', () => {
        expect(tokenize('createdBy:"Ada Lovelace" revenue').map((t) => t.raw)).toEqual([
            'createdBy:"Ada Lovelace"',
            'revenue',
        ])
    })

    test.each([
        ['empty input', '', 0, [], 'empty'],
        ['chips but no text is not empty', '', 0, [chip('is', 'insight')], 'text'],
        ['partial key', 'createdB', 8, [], 'key'],
        ['partial key with negation', '-cr', 3, [], 'key'],
        ['key alias is case-insensitive', 'CREATEDBY:ca', 12, [], 'value'],
        ['unknown key is free text', 'error: timeout', 6, [], 'text'],
        ['plain words', 'revenue', 7, [], 'text'],
        ['cursor in whitespace', 'is:insight ', 11, [], 'text'],
    ])('cursor context: %s', (_, text, cursor, chips, kind) => {
        expect(getCursorContext(text, cursor, chips).kind).toBe(kind)
    })

    test('key suggest lists every key that starts with the prefix, by canonical key', () => {
        const context = getCursorContext('c', 1, [])
        expect(context.kind === 'key' && context.matches.map((m) => m.key)).toEqual(['createdBy'])
    })

    test('value matching puts prefix matches before substring matches', () => {
        expect(matchValueOptions(TYPE_OPTIONS, 'fe', { allowSubstring: true }).map((o) => o.value)).toEqual([
            'feature_flag',
            'early_access_feature',
        ])
        expect(matchValueOptions(TYPE_OPTIONS, 'ash', { allowSubstring: true }).map((o) => o.value)).toEqual([
            'dashboard',
        ])
        expect(matchValueOptions(TYPE_OPTIONS, 'ash', { allowSubstring: false })).toEqual([])
    })

    test.each([
        ['exact value with nothing else starting with it', TYPE_OPTIONS, 'dashboard', 'dashboard'],
        ['alias names the option', TYPE_OPTIONS, 'flag', 'feature_flag'],
        ['partial value waits', TYPE_OPTIONS, 'dash', null],
        ['exact value that another option extends waits', USER_OPTIONS, 'me', null],
        ['longer exact value commits', USER_OPTIONS, 'mel', 'mel@example.com'],
    ])('typed value commits without Space: %s', (_, options, value, expected) => {
        expect(unambiguousOption(options, value)?.value ?? null).toBe(expected)
    })

    test.each([
        ['at the start', '', 0, ' ', 1, true],
        ['after a space', 'a ', 2, 'a  ', 3, true],
        ['between words', 'a', 1, 'a ', 2, false],
    ])('a space typed %s is redundant: %s', (_, previousText, previousCursor, text, cursor, expected) => {
        expect(isRedundantSpace({ previousText, previousCursor, text, cursor })).toBe(expected)
    })

    test('pasted query turns valid filters into one chip per key, last value wins, and keeps the rest as text', () => {
        const result = extractChips('is:flag createdBy:me is:insight is:banana checkout', [], OPTIONS)
        expect(result.chips.map((c) => `${c.key}:${c.value}`)).toEqual(['is:insight', 'createdBy:me'])
        expect(result.text).toBe('is:banana checkout')
    })

    test.each([
        [
            'maps friendly keys, sorts filters, drops invalid values',
            'createdBy:Ca is:banana revenue',
            [chip('is', 'dashboard', true)],
            '-type:dashboard user:Ca revenue',
            'revenue',
            2,
        ],
        [
            "a typed value stands in for that key's chip",
            'is:flag',
            [chip('is', 'dashboard')],
            'type:feature_flag',
            '',
            1,
        ],
        ['quotes values with spaces', '', [chip('createdBy', 'Ada Lovelace')], 'user:"Ada Lovelace"', '', 1],
        ['free text only', 'revenue chart', [], 'revenue chart', 'revenue chart', 0],
    ])('resolves the query: %s', (_, text, chips, backendSearch, freeText, filterCount) => {
        const resolved = resolveQuery(text, chips, OPTIONS)
        expect(resolved).toMatchObject({ backendSearch, freeText })
        expect(resolved.filters).toHaveLength(filterCount)
    })

    test.each([
        ['typed space after a valid value', 'is:insight', 10, 'is:insight ', 11, 'is:insight', 'space'],
        ['typed space inside an open quote', 'createdBy:"Ada', 14, 'createdBy:"Ada ', 15, null, null],
        ['typed space after an invalid value', 'is:banana', 9, 'is:banana ', 10, null, null],
        [
            'typed the last letter of an unambiguous value',
            'is:dashboar',
            11,
            'is:dashboard',
            12,
            'is:dashboard',
            'typed',
        ],
        ['typed a value another option extends', 'createdBy:m', 11, 'createdBy:me', 12, null, null],
        ['typed the last letter inside an open quote', 'is:"dashboar', 12, 'is:"dashboard', 13, null, null],
        ['typed the closing quote', 'is:"dashboard', 13, 'is:"dashboard"', 14, 'is:dashboard', 'typed'],
    ])(
        'commits a chip from an edit: %s',
        (_, previousText, previousCursor, text, cursor, expectedChip, expectedVia) => {
            const committed = chipCommittedByEdit({ previousText, previousCursor, text, cursor }, [], OPTIONS)
            expect(committed ? `${committed.chip.key}:${committed.chip.value}` : null).toBe(expectedChip)
            expect(committed?.via ?? null).toBe(expectedVia)
        }
    )

    test('ask AI text includes chips as typed text', () => {
        expect(queryAsText(' revenue ', [chip('is', 'dashboard', true)])).toBe('-is:dashboard revenue')
    })

    test('removing a token keeps one space between neighbours and puts the cursor there', () => {
        const text = 'a is:insight b'
        const token = tokenize(text)[1]
        expect(removeToken(text, token)).toEqual({ text: 'a b', cursor: 2 })
    })
})
