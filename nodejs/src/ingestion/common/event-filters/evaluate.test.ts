import { evaluateFilterTree, treeHasConditions } from './evaluate'
import { FilterNode } from './schema'

describe('evaluateFilterTree', () => {
    describe('empty groups are conservative (never drop)', () => {
        it('empty AND returns false', () => {
            expect(evaluateFilterTree({ type: 'and', children: [] }, { event_name: '$pageview' })).toBe(false)
        })

        it('empty OR returns false', () => {
            expect(evaluateFilterTree({ type: 'or', children: [] }, { event_name: '$pageview' })).toBe(false)
        })

        it('NOT wrapping empty AND returns true', () => {
            expect(evaluateFilterTree({ type: 'not', child: { type: 'and', children: [] } }, { event_name: 'x' })).toBe(
                true
            )
        })

        it('NOT wrapping empty OR returns true', () => {
            expect(evaluateFilterTree({ type: 'not', child: { type: 'or', children: [] } }, { event_name: 'x' })).toBe(
                true
            )
        })

        it('AND with only empty child groups returns false', () => {
            const node: FilterNode = {
                type: 'and',
                children: [
                    { type: 'or', children: [] },
                    { type: 'or', children: [] },
                ],
            }
            expect(evaluateFilterTree(node, { event_name: '$pageview' })).toBe(false)
        })
    })

    describe('condition matching', () => {
        it('exact match on event_name', () => {
            const node: FilterNode = { type: 'condition', field: 'event_name', operator: 'exact', value: '$pageview' }
            expect(evaluateFilterTree(node, { event_name: '$pageview' })).toBe(true)
            expect(evaluateFilterTree(node, { event_name: '$click' })).toBe(false)
        })

        it('exact match on distinct_id', () => {
            const node: FilterNode = { type: 'condition', field: 'distinct_id', operator: 'exact', value: 'bot-1' }
            expect(evaluateFilterTree(node, { distinct_id: 'bot-1' })).toBe(true)
            expect(evaluateFilterTree(node, { distinct_id: 'user-1' })).toBe(false)
        })

        it('contains match', () => {
            const node: FilterNode = { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot-' }
            expect(evaluateFilterTree(node, { distinct_id: 'bot-crawler' })).toBe(true)
            expect(evaluateFilterTree(node, { distinct_id: 'real-user' })).toBe(false)
        })

        it('returns false for missing field', () => {
            const node: FilterNode = { type: 'condition', field: 'distinct_id', operator: 'exact', value: 'test' }
            expect(evaluateFilterTree(node, { event_name: '$pageview' })).toBe(false)
        })

        it('returns false for undefined field', () => {
            const node: FilterNode = { type: 'condition', field: 'event_name', operator: 'exact', value: 'test' }
            expect(evaluateFilterTree(node, {})).toBe(false)
        })
    })

    describe('boolean logic', () => {
        it('AND requires all children to match', () => {
            const node: FilterNode = {
                type: 'and',
                children: [
                    { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
                    { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot-' },
                ],
            }
            expect(evaluateFilterTree(node, { event_name: '$internal', distinct_id: 'bot-x' })).toBe(true)
            expect(evaluateFilterTree(node, { event_name: '$internal', distinct_id: 'user' })).toBe(false)
            expect(evaluateFilterTree(node, { event_name: '$other', distinct_id: 'bot-x' })).toBe(false)
        })

        it('OR requires any child to match', () => {
            const node: FilterNode = {
                type: 'or',
                children: [
                    { type: 'condition', field: 'event_name', operator: 'exact', value: 'a' },
                    { type: 'condition', field: 'event_name', operator: 'exact', value: 'b' },
                ],
            }
            expect(evaluateFilterTree(node, { event_name: 'a' })).toBe(true)
            expect(evaluateFilterTree(node, { event_name: 'b' })).toBe(true)
            expect(evaluateFilterTree(node, { event_name: 'c' })).toBe(false)
        })

        it('NOT inverts result', () => {
            const node: FilterNode = {
                type: 'not',
                child: { type: 'condition', field: 'event_name', operator: 'exact', value: 'keep' },
            }
            expect(evaluateFilterTree(node, { event_name: 'keep' })).toBe(false)
            expect(evaluateFilterTree(node, { event_name: 'other' })).toBe(true)
        })
    })

    describe('complex trees', () => {
        it('OR of AND groups', () => {
            const node: FilterNode = {
                type: 'or',
                children: [
                    { type: 'condition', field: 'event_name', operator: 'exact', value: '$drop_me' },
                    {
                        type: 'and',
                        children: [
                            { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
                            { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot-' },
                        ],
                    },
                ],
            }
            expect(evaluateFilterTree(node, { event_name: '$drop_me', distinct_id: 'anyone' })).toBe(true)
            expect(evaluateFilterTree(node, { event_name: '$internal', distinct_id: 'bot-x' })).toBe(true)
            expect(evaluateFilterTree(node, { event_name: '$internal', distinct_id: 'user' })).toBe(false)
            expect(evaluateFilterTree(node, { event_name: '$pageview', distinct_id: 'bot-x' })).toBe(false)
        })

        it('NOT wrapping OR (allowlist pattern)', () => {
            const node: FilterNode = {
                type: 'not',
                child: {
                    type: 'or',
                    children: [
                        { type: 'condition', field: 'event_name', operator: 'exact', value: 'allowed_1' },
                        { type: 'condition', field: 'event_name', operator: 'exact', value: 'allowed_2' },
                    ],
                },
            }
            expect(evaluateFilterTree(node, { event_name: 'allowed_1' })).toBe(false)
            expect(evaluateFilterTree(node, { event_name: 'allowed_2' })).toBe(false)
            expect(evaluateFilterTree(node, { event_name: 'other' })).toBe(true)
        })
    })
})

describe('treeHasConditions', () => {
    it('returns false for empty groups', () => {
        expect(treeHasConditions({ type: 'or', children: [] })).toBe(false)
        expect(treeHasConditions({ type: 'and', children: [] })).toBe(false)
    })

    it('returns true for a condition', () => {
        expect(treeHasConditions({ type: 'condition', field: 'event_name', operator: 'exact', value: 'x' })).toBe(true)
    })

    it('returns true for nested condition', () => {
        expect(
            treeHasConditions({
                type: 'or',
                children: [
                    {
                        type: 'and',
                        children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: 'x' }],
                    },
                ],
            })
        ).toBe(true)
    })

    it('returns false for nested empty groups', () => {
        expect(
            treeHasConditions({ type: 'or', children: [{ type: 'and', children: [{ type: 'or', children: [] }] }] })
        ).toBe(false)
    })

    it('returns true for NOT wrapping condition', () => {
        expect(
            treeHasConditions({
                type: 'not',
                child: { type: 'condition', field: 'event_name', operator: 'exact', value: 'x' },
            })
        ).toBe(true)
    })

    it('returns false for NOT wrapping empty group', () => {
        expect(treeHasConditions({ type: 'not', child: { type: 'or', children: [] } })).toBe(false)
    })
})
