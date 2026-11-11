import { EventFilterRowSchema, FilterNodeSchema } from './schema'

describe('FilterNodeSchema', () => {
    it('accepts a valid condition', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'condition',
            field: 'event_name',
            operator: 'exact',
            value: '$pageview',
        })
        expect(result.success).toBe(true)
    })

    it('rejects condition with empty value', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'condition',
            field: 'event_name',
            operator: 'exact',
            value: '',
        })
        expect(result.success).toBe(false)
    })

    it('rejects condition with invalid field', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'condition',
            field: 'session_id',
            operator: 'exact',
            value: 'test',
        })
        expect(result.success).toBe(false)
    })

    it('rejects condition with invalid operator', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'condition',
            field: 'event_name',
            operator: 'regex',
            value: 'test',
        })
        expect(result.success).toBe(false)
    })

    it('accepts a valid AND group', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'and',
            children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: 'test' }],
        })
        expect(result.success).toBe(true)
    })

    it('accepts an empty AND group', () => {
        const result = FilterNodeSchema.safeParse({ type: 'and', children: [] })
        expect(result.success).toBe(true)
    })

    it('accepts a valid OR group', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'or',
            children: [{ type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot' }],
        })
        expect(result.success).toBe(true)
    })

    it('accepts a valid NOT node', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'not',
            child: { type: 'condition', field: 'event_name', operator: 'exact', value: 'test' },
        })
        expect(result.success).toBe(true)
    })

    it('rejects NOT without child', () => {
        const result = FilterNodeSchema.safeParse({ type: 'not' })
        expect(result.success).toBe(false)
    })

    it('accepts deeply nested tree', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'or',
            children: [
                {
                    type: 'not',
                    child: {
                        type: 'and',
                        children: [
                            { type: 'condition', field: 'event_name', operator: 'exact', value: 'a' },
                            { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'b' },
                        ],
                    },
                },
                { type: 'condition', field: 'event_name', operator: 'exact', value: 'c' },
            ],
        })
        expect(result.success).toBe(true)
    })

    it('rejects unknown node type', () => {
        const result = FilterNodeSchema.safeParse({ type: 'xor', children: [] })
        expect(result.success).toBe(false)
    })

    it('rejects invalid child in group', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'and',
            children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: '' }],
        })
        expect(result.success).toBe(false)
    })

    it('rejects condition missing field', () => {
        const result = FilterNodeSchema.safeParse({ type: 'condition', operator: 'exact', value: 'x' })
        expect(result.success).toBe(false)
    })

    it('rejects condition missing operator', () => {
        const result = FilterNodeSchema.safeParse({ type: 'condition', field: 'event_name', value: 'x' })
        expect(result.success).toBe(false)
    })

    it('rejects condition missing value', () => {
        const result = FilterNodeSchema.safeParse({ type: 'condition', field: 'event_name', operator: 'exact' })
        expect(result.success).toBe(false)
    })

    it('rejects condition with non-string value', () => {
        const result = FilterNodeSchema.safeParse({
            type: 'condition',
            field: 'event_name',
            operator: 'exact',
            value: 123,
        })
        expect(result.success).toBe(false)
    })

    it('rejects missing type', () => {
        const result = FilterNodeSchema.safeParse({ children: [] })
        expect(result.success).toBe(false)
    })

    it('rejects non-object node', () => {
        const result = FilterNodeSchema.safeParse('string')
        expect(result.success).toBe(false)
    })

    it('rejects AND with non-list children', () => {
        const result = FilterNodeSchema.safeParse({ type: 'and', children: 'not_a_list' })
        expect(result.success).toBe(false)
    })

    it('rejects OR with non-list children', () => {
        const result = FilterNodeSchema.safeParse({ type: 'or', children: 'not_a_list' })
        expect(result.success).toBe(false)
    })
})

describe('EventFilterRowSchema', () => {
    it('accepts a valid row with live mode', () => {
        const result = EventFilterRowSchema.safeParse({
            id: 'abc-123',
            team_id: 1,
            mode: 'live',
            filter_tree: {
                type: 'or',
                children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: '$drop' }],
            },
        })
        expect(result.success).toBe(true)
    })

    it('accepts a valid row with dry_run mode', () => {
        const result = EventFilterRowSchema.safeParse({
            id: 'abc-123',
            team_id: 1,
            mode: 'dry_run',
            filter_tree: { type: 'or', children: [] },
        })
        expect(result.success).toBe(true)
    })

    it('rejects row with missing mode', () => {
        const result = EventFilterRowSchema.safeParse({
            id: 'abc-123',
            team_id: 1,
            filter_tree: { type: 'or', children: [] },
        })
        expect(result.success).toBe(false)
    })

    it('rejects row with invalid mode', () => {
        const result = EventFilterRowSchema.safeParse({
            id: 'abc-123',
            team_id: 1,
            mode: 'turbo',
            filter_tree: { type: 'or', children: [] },
        })
        expect(result.success).toBe(false)
    })

    it('rejects row with missing team_id', () => {
        const result = EventFilterRowSchema.safeParse({
            id: 'abc-123',
            mode: 'live',
            filter_tree: { type: 'or', children: [] },
        })
        expect(result.success).toBe(false)
    })

    it('rejects row with invalid filter_tree', () => {
        const result = EventFilterRowSchema.safeParse({
            id: 'abc-123',
            team_id: 1,
            mode: 'live',
            filter_tree: { type: 'bad' },
        })
        expect(result.success).toBe(false)
    })
})
