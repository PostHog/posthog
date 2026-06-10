import { isTreeEmpty, filterTreeToExpression, nodeSummary } from './filterTreeDisplay'
import { cond, and, or, not } from './testHelpers'

describe('isTreeEmpty', () => {
    it.each([
        ['condition is not empty', cond(), false],
        ['empty or', or(), true],
        ['empty and', and(), true],
        ['not wrapping empty group', not(or()), true],
        ['not wrapping condition', not(cond()), false],
        ['group with condition', or(cond()), false],
        ['nested empty groups recurse', or(and()), true],
        ['nested empty groups mixed with condition', or(and(), cond()), false],
    ])('%s', (_name, tree, expected) => {
        expect(isTreeEmpty(tree)).toBe(expected)
    })
})

describe('filterTreeToExpression', () => {
    it('renders a simple condition', () => {
        expect(filterTreeToExpression(cond('event_name', 'exact', '$pageview'))).toBe('event_name = "$pageview"')
    })

    it('renders contains as ~', () => {
        expect(filterTreeToExpression(cond('distinct_id', 'contains', 'bot'))).toBe('distinct_id ~ "bot"')
    })

    it('renders AND group with tree connectors', () => {
        const tree = and(cond('event_name', 'exact', 'a'), cond('distinct_id', 'exact', 'u1'))
        expect(filterTreeToExpression(tree)).toBe(['AND', '├── event_name = "a"', '└── distinct_id = "u1"'].join('\n'))
    })

    it('renders OR group with tree connectors', () => {
        const tree = or(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b'))
        expect(filterTreeToExpression(tree)).toBe(['OR', '├── event_name = "a"', '└── event_name = "b"'].join('\n'))
    })

    it('renders NOT with child', () => {
        expect(filterTreeToExpression(not(cond('event_name', 'exact', 'x')))).toBe(
            ['NOT', '└── event_name = "x"'].join('\n')
        )
    })

    it('renders empty group', () => {
        expect(filterTreeToExpression(or())).toBe('OR (empty)')
    })

    it('renders nested AND inside OR', () => {
        const tree = or(
            cond('event_name', 'exact', 'a'),
            and(cond('event_name', 'exact', 'b'), cond('distinct_id', 'contains', 'bot'))
        )
        expect(filterTreeToExpression(tree)).toBe(
            ['OR', '├── event_name = "a"', '└── AND', '    ├── event_name = "b"', '    └── distinct_id ~ "bot"'].join(
                '\n'
            )
        )
    })

    it('renders NOT wrapping a group', () => {
        const tree = not(and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')))
        expect(filterTreeToExpression(tree)).toBe(
            ['NOT', '└── AND', '    ├── event_name = "a"', '    └── event_name = "b"'].join('\n')
        )
    })

    it('renders deeply nested tree', () => {
        const tree = or(
            cond('event_name', 'exact', '$drop_me'),
            and(cond('event_name', 'exact', '$internal'), not(cond('distinct_id', 'contains', 'admin')))
        )
        expect(filterTreeToExpression(tree)).toBe(
            [
                'OR',
                '├── event_name = "$drop_me"',
                '└── AND',
                '    ├── event_name = "$internal"',
                '    └── NOT',
                '        └── distinct_id ~ "admin"',
            ].join('\n')
        )
    })
})

describe('nodeSummary', () => {
    it('summarizes a condition', () => {
        expect(nodeSummary(cond('event_name', 'exact', '$pageview'))).toBe('event_name exact "$pageview"')
    })

    it('summarizes a NOT node', () => {
        expect(nodeSummary(not(cond()))).toBe('NOT (...)')
    })

    it('summarizes an AND group with count', () => {
        expect(nodeSummary(and(cond(), cond(), cond()))).toBe('AND group (3 items)')
    })

    it('summarizes an empty OR group', () => {
        expect(nodeSummary(or())).toBe('OR group (0 items)')
    })
})
