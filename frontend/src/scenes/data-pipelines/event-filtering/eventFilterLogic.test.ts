import { evaluateFilterTree, treeHasConditions, treeHasEmptyValues, FilterNode } from './eventFilterLogic'

function cond(
    field: 'event_name' | 'distinct_id' = 'event_name',
    operator: 'exact' | 'contains' = 'exact',
    value: string = 'pageview'
): FilterNode {
    return { type: 'condition', field, operator, value }
}

function and(...children: FilterNode[]): FilterNode {
    return { type: 'and', children }
}

function or(...children: FilterNode[]): FilterNode {
    return { type: 'or', children }
}

function not(child: FilterNode): FilterNode {
    return { type: 'not', child }
}

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

describe('treeHasEmptyValues', () => {
    it.each([
        ['filled condition', cond('event_name', 'exact', 'pageview'), false],
        ['empty value', cond('event_name', 'exact', ''), true],
        ['whitespace only', cond('event_name', 'exact', '  '), true],
        ['nested empty in and', and(cond(), cond('event_name', 'exact', '')), true],
        ['nested empty in not', not(cond('event_name', 'exact', '')), true],
        ['all filled in group', and(cond(), cond('distinct_id', 'exact', 'u1')), false],
    ])('%s', (_name, tree, expected) => {
        expect(treeHasEmptyValues(tree)).toBe(expected)
    })
})
