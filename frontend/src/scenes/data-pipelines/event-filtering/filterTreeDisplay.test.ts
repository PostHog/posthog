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
        ['nested empty groups (not recursive — has a child node)', or(and()), false],
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

    it('renders OR group', () => {
        const tree = or(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b'))
        expect(filterTreeToExpression(tree)).toBe('event_name = "a"\nOR\nevent_name = "b"')
    })

    it('renders AND group', () => {
        const tree = and(cond('event_name', 'exact', 'a'), cond('distinct_id', 'exact', 'u1'))
        expect(filterTreeToExpression(tree)).toBe('event_name = "a"\nAND\ndistinct_id = "u1"')
    })

    it('renders NOT with simple child inline', () => {
        expect(filterTreeToExpression(not(cond('event_name', 'exact', 'x')))).toBe('NOT (event_name = "x")')
    })

    it('renders empty group', () => {
        expect(filterTreeToExpression(or())).toBe('(empty)')
    })

    it('collapses single-child group', () => {
        expect(filterTreeToExpression(or(cond('event_name', 'exact', 'a')))).toBe('event_name = "a"')
    })

    it('renders NOT wrapping a group (multi-line)', () => {
        const tree = not(and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')))
        expect(filterTreeToExpression(tree)).toBe('NOT (\n  event_name = "a"\n  AND\n  event_name = "b"\n)')
    })

    it('parenthesizes AND inside OR', () => {
        const tree = or(
            cond('event_name', 'exact', 'a'),
            and(cond('event_name', 'exact', 'b'), cond('event_name', 'exact', 'c'))
        )
        expect(filterTreeToExpression(tree)).toBe(
            'event_name = "a"\nOR\n(\n  event_name = "b"\n  AND\n  event_name = "c"\n)'
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
