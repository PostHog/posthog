import {
    countConditions,
    evaluateFilterTree,
    FilterNode,
    normalizeRootToGroup,
    treeHasConditions,
    treeHasEmptyValues,
    updateAtPath,
} from './eventFilterLogic'
import { cond, and, or, not } from './testHelpers'

describe('evaluateFilterTree', () => {
    describe('condition nodes', () => {
        it.each([
            ['exact match', cond('event_name', 'exact', 'pageview'), { event_name: 'pageview' }, true],
            ['exact no match', cond('event_name', 'exact', 'pageview'), { event_name: 'click' }, false],
            ['contains match', cond('event_name', 'contains', 'view'), { event_name: 'pageview' }, true],
            ['contains no match', cond('event_name', 'contains', 'click'), { event_name: 'pageview' }, false],
            ['missing field', cond('event_name', 'exact', 'pageview'), {}, false],
            ['distinct_id match', cond('distinct_id', 'exact', 'u1'), { distinct_id: 'u1' }, true],
            ['empty string field matches empty value', cond('event_name', 'exact', ''), { event_name: '' }, true],
            ['empty string field contains empty', cond('event_name', 'contains', ''), { event_name: 'anything' }, true],
        ])('%s', (_name, tree, event, expected) => {
            expect(evaluateFilterTree(tree, event)).toBe(expected)
        })
    })

    describe('AND nodes', () => {
        it('all true', () => {
            const tree = and(cond('event_name', 'exact', 'pageview'), cond('distinct_id', 'exact', 'u1'))
            expect(evaluateFilterTree(tree, { event_name: 'pageview', distinct_id: 'u1' })).toBe(true)
        })

        it('one false', () => {
            const tree = and(cond('event_name', 'exact', 'pageview'), cond('distinct_id', 'exact', 'u1'))
            expect(evaluateFilterTree(tree, { event_name: 'pageview', distinct_id: 'u2' })).toBe(false)
        })

        it('empty children returns false', () => {
            expect(evaluateFilterTree(and(), {})).toBe(false)
        })
    })

    describe('OR nodes', () => {
        it('one true', () => {
            const tree = or(cond('event_name', 'exact', 'pageview'), cond('event_name', 'exact', 'click'))
            expect(evaluateFilterTree(tree, { event_name: 'click' })).toBe(true)
        })

        it('none true', () => {
            const tree = or(cond('event_name', 'exact', 'pageview'), cond('event_name', 'exact', 'click'))
            expect(evaluateFilterTree(tree, { event_name: 'submit' })).toBe(false)
        })

        it('empty children returns false', () => {
            expect(evaluateFilterTree(or(), {})).toBe(false)
        })
    })

    describe('NOT nodes', () => {
        it('inverts true to false', () => {
            expect(evaluateFilterTree(not(cond('event_name', 'exact', 'pageview')), { event_name: 'pageview' })).toBe(
                false
            )
        })

        it('inverts false to true', () => {
            expect(evaluateFilterTree(not(cond('event_name', 'exact', 'pageview')), { event_name: 'click' })).toBe(true)
        })
    })

    describe('complex tree', () => {
        // Drop if: (event is "$autocapture" OR event contains "bot_")
        //          AND NOT (distinct_id is "admin-user")
        const tree = and(
            or(cond('event_name', 'exact', '$autocapture'), cond('event_name', 'contains', 'bot_')),
            not(cond('distinct_id', 'exact', 'admin-user'))
        )

        it.each([
            ['$autocapture from regular user -> drop', { event_name: '$autocapture', distinct_id: 'user-1' }, true],
            ['bot_ event from regular user -> drop', { event_name: 'bot_heartbeat', distinct_id: 'user-2' }, true],
            ['$autocapture from admin -> ingest', { event_name: '$autocapture', distinct_id: 'admin-user' }, false],
            ['bot_ event from admin -> ingest', { event_name: 'bot_ping', distinct_id: 'admin-user' }, false],
            ['normal event from regular user -> ingest', { event_name: 'purchase', distinct_id: 'user-1' }, false],
            ['normal event from admin -> ingest', { event_name: 'login', distinct_id: 'admin-user' }, false],
            [
                'partial match on bot_ via contains -> drop',
                { event_name: 'internal_bot_check', distinct_id: 'service-1' },
                true,
            ],
            ['event_name missing -> ingest', { distinct_id: 'user-1' }, false],
            ['distinct_id missing -> drop', { event_name: '$autocapture' }, true],
        ])('%s', (_name, event, expected) => {
            expect(evaluateFilterTree(tree, event)).toBe(expected)
        })
    })

    describe('double negation', () => {
        it('NOT(NOT(condition)) evaluates to the original condition result', () => {
            const tree = not(not(cond('event_name', 'exact', 'pageview')))
            expect(evaluateFilterTree(tree, { event_name: 'pageview' })).toBe(true)
            expect(evaluateFilterTree(tree, { event_name: 'click' })).toBe(false)
        })
    })

    describe('deeply nested tree (4 levels)', () => {
        // OR(AND(NOT(condition), condition), condition)
        const tree = or(
            and(not(cond('event_name', 'contains', 'internal')), cond('distinct_id', 'contains', 'bot')),
            cond('event_name', 'exact', '$drop_me')
        )

        it.each([
            ['matches second OR branch', { event_name: '$drop_me', distinct_id: 'user-1' }, true],
            ['matches first OR branch (not internal + bot)', { event_name: 'ping', distinct_id: 'bot-1' }, true],
            ['blocked by NOT (internal + bot)', { event_name: 'internal_check', distinct_id: 'bot-1' }, false],
            ['no match at all', { event_name: 'click', distinct_id: 'user-1' }, false],
        ])('%s', (_name, event, expected) => {
            expect(evaluateFilterTree(tree, event)).toBe(expected)
        })
    })
})

describe('updateAtPath', () => {
    const replacement = cond('distinct_id', 'exact', 'replaced')

    describe('root updates (empty path)', () => {
        it('replaces the entire tree', () => {
            const tree = cond()
            const result = updateAtPath(tree, [], () => replacement)
            expect(result).toEqual(replacement)
        })

        it('wraps root in NOT', () => {
            const tree = cond()
            const result = updateAtPath(tree, [], (node) => not(node))
            expect(result).toEqual(not(cond()))
        })

        it('converts root condition to a group', () => {
            const tree = cond()
            const result = updateAtPath(tree, [], (node) => and(node))
            expect(result).toEqual(and(cond()))
        })
    })

    describe('updating children in AND/OR groups', () => {
        it('updates first child of an OR group', () => {
            const tree = or(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b'))
            const result = updateAtPath(tree, [0], () => replacement)
            expect(result).toEqual(or(replacement, cond('event_name', 'exact', 'b')))
        })

        it('updates second child of an AND group', () => {
            const tree = and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b'))
            const result = updateAtPath(tree, [1], () => replacement)
            expect(result).toEqual(and(cond('event_name', 'exact', 'a'), replacement))
        })

        it('adds a child to a group via updater', () => {
            const tree = or(cond())
            const result = updateAtPath(tree, [], (node) => {
                if (node.type === 'or') {
                    return { ...node, children: [...node.children, replacement] }
                }
                return node
            })
            expect(result).toEqual(or(cond(), replacement))
        })

        it('removes a child from a group via updater', () => {
            const tree = and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b'))
            const result = updateAtPath(tree, [], (node) => {
                if (node.type === 'and') {
                    return { ...node, children: node.children.filter((_, i) => i !== 0) }
                }
                return node
            })
            expect(result).toEqual(and(cond('event_name', 'exact', 'b')))
        })
    })

    describe('updating through NOT nodes', () => {
        it('updates the child of a NOT node', () => {
            const tree = not(cond())
            const result = updateAtPath(tree, ['child'], () => replacement)
            expect(result).toEqual(not(replacement))
        })

        it('unwraps a NOT by returning its child', () => {
            const inner = cond()
            const tree = not(inner)
            const result = updateAtPath(tree, [], (node) => {
                if (node.type === 'not') {
                    return node.child
                }
                return node
            })
            expect(result).toEqual(inner)
        })
    })

    describe('deep nested paths', () => {
        // AND(OR(condA, condB), NOT(condC))
        const condA = cond('event_name', 'exact', 'a')
        const condB = cond('event_name', 'exact', 'b')
        const condC = cond('distinct_id', 'exact', 'c')
        const tree = and(or(condA, condB), not(condC))

        it('updates condA at [0, 0]', () => {
            const result = updateAtPath(tree, [0, 0], () => replacement)
            expect(result).toEqual(and(or(replacement, condB), not(condC)))
        })

        it('updates condB at [0, 1]', () => {
            const result = updateAtPath(tree, [0, 1], () => replacement)
            expect(result).toEqual(and(or(condA, replacement), not(condC)))
        })

        it('updates condC through NOT at [1, "child"]', () => {
            const result = updateAtPath(tree, [1, 'child'], () => replacement)
            expect(result).toEqual(and(or(condA, condB), not(replacement)))
        })

        it('wraps a nested condition in NOT', () => {
            const result = updateAtPath(tree, [0, 0], (node) => not(node))
            expect(result).toEqual(and(or(not(condA), condB), not(condC)))
        })

        it('replaces the OR subgroup entirely', () => {
            const result = updateAtPath(tree, [0], () => replacement)
            expect(result).toEqual(and(replacement, not(condC)))
        })
    })

    describe('edge cases', () => {
        it('out-of-bounds index returns node unchanged', () => {
            const tree = or(cond())
            const result = updateAtPath(tree, [5], () => replacement)
            expect(result).toEqual(tree)
        })

        it('numeric step on NOT node returns node unchanged', () => {
            const tree = not(cond())
            const result = updateAtPath(tree, [0], () => replacement)
            expect(result).toEqual(tree)
        })

        it('"child" step on group node returns node unchanged', () => {
            const tree = and(cond())
            const result = updateAtPath(tree, ['child'], () => replacement)
            expect(result).toEqual(tree)
        })
    })

    describe('immutability', () => {
        it('does not mutate the original tree', () => {
            const tree = and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b'))
            const original = JSON.parse(JSON.stringify(tree))
            updateAtPath(tree, [0], () => replacement)
            expect(tree).toEqual(original)
        })

        it('shares unchanged subtrees by reference', () => {
            const child0 = cond('event_name', 'exact', 'a')
            const child1 = cond('event_name', 'exact', 'b')
            const tree = or(child0, child1)
            const result = updateAtPath(tree, [0], () => replacement)
            // child1 should be the same reference — not copied
            expect((result as { type: 'or'; children: FilterNode[] }).children[1]).toBe(child1)
        })
    })
})

describe('normalizeRootToGroup', () => {
    // Regression: the backend prunes single-child groups, so a saved one-condition
    // filter loads back as a bare condition (or NOT) with no group to host the
    // "Add condition"/"Add group" buttons. Re-wrap any non-group root in an OR.
    it.each([
        ['bare condition', cond('distinct_id', 'contains', 'bot')],
        ['NOT node', not(cond())],
    ])('wraps a %s root in an OR group', (_name, node) => {
        expect(normalizeRootToGroup(node)).toEqual(or(node))
    })

    it.each([
        ['OR', or(cond(), cond('distinct_id', 'exact', 'u1'))],
        ['AND', and(cond())],
    ])('leaves an %s root unchanged (same reference)', (_name, tree) => {
        expect(normalizeRootToGroup(tree)).toBe(tree)
    })
})

describe('treeHasConditions', () => {
    it.each([
        ['bare condition', cond(), true],
        ['nested condition', and(cond()), true],
        ['not condition', not(cond()), true],
        ['empty and', and(), false],
        ['empty or', or(), false],
        ['not with empty child', not(or()), false],
    ])('%s', (_name, tree, expected) => {
        expect(treeHasConditions(tree)).toBe(expected)
    })
})

describe('countConditions', () => {
    it.each([
        ['bare condition', cond(), 1],
        ['empty and', and(), 0],
        ['empty or', or(), 0],
        ['flat or of three', or(cond(), cond(), cond()), 3],
        ['nested and inside or', or(cond(), and(cond(), cond())), 3],
        ['not wrapping condition', not(cond()), 1],
        ['not wrapping empty group', not(or()), 0],
        ['deeply nested', and(or(cond(), not(cond())), and(cond())), 3],
    ])('%s', (_name, tree, expected) => {
        expect(countConditions(tree)).toBe(expected)
    })
})

describe('treeHasEmptyValues', () => {
    it.each([
        ['filled condition', cond('event_name', 'exact', 'pageview'), false],
        ['empty value', cond('event_name', 'exact', ''), true],
        ['whitespace only', cond('event_name', 'exact', '  '), true],
        ['nested empty in and', and(cond(), cond('event_name', 'exact', '')), true],
        ['nested empty in not', not(cond('event_name', 'exact', '')), true],
        ['all filled in group', and(cond(), cond('distinct_id', 'exact', 'u1')), false],
        ['empty group has no empty values', or(), false],
        ['deeply nested empty value', and(or(cond(), not(cond('event_name', 'exact', '')))), true],
    ])('%s', (_name, tree, expected) => {
        expect(treeHasEmptyValues(tree)).toBe(expected)
    })
})
