import { z } from 'zod'

const FilterConditionSchema = z.object({
    type: z.literal('condition'),
    field: z.enum(['event_name', 'distinct_id']),
    operator: z.enum(['exact', 'contains']),
    value: z.string().min(1),
})

export const FilterNodeSchema: z.ZodType<FilterNode> = z.lazy(() =>
    z.discriminatedUnion('type', [
        FilterConditionSchema,
        z.object({
            type: z.literal('and'),
            children: z.array(FilterNodeSchema),
        }),
        z.object({
            type: z.literal('or'),
            children: z.array(FilterNodeSchema),
        }),
        z.object({
            type: z.literal('not'),
            child: FilterNodeSchema,
        }),
    ])
)

export const EventFilterModeSchema = z.enum(['disabled', 'dry_run', 'live'])
export type EventFilterMode = z.infer<typeof EventFilterModeSchema>

export const EventFilterRowSchema = z.object({
    id: z.string(),
    team_id: z.number(),
    mode: EventFilterModeSchema,
    filter_tree: FilterNodeSchema,
})

// Inferred types from the schema
export type FilterConditionNode = z.infer<typeof FilterConditionSchema>
export type FilterNode = z.infer<typeof FilterConditionSchema> | FilterAndNode | FilterOrNode | FilterNotNode

export interface FilterAndNode {
    type: 'and'
    children: FilterNode[]
}

export interface FilterOrNode {
    type: 'or'
    children: FilterNode[]
}

export interface FilterNotNode {
    type: 'not'
    child: FilterNode
}

export interface EventFilterRule {
    id: string
    team_id: number
    mode: EventFilterMode
    filter_tree: FilterNode
}
