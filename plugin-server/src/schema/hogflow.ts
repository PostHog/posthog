import { z } from 'zod'

const _commonActionFields = {
    id: z.string(),
    name: z.string(),
    description: z.string(),
    on_error: z.enum(['continue', 'abort', 'complete', 'branch']).optional(),
    created_at: z.number(),
    updated_at: z.number(),
}

const HogFlowActionSchema = z.discriminatedUnion('type', [
    z.object({
        ..._commonActionFields,
        type: z.literal('trigger'),
        config: z.object({
            filters: z.any(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('conditional_branch'),
        config: z.object({
            conditions: z.array(
                z.object({
                    filter: z.any(), // type this stronger
                    on_match: z.string(), // TODO: Can we type this more directly to an edge?
                })
            ),
            delay_duration: z.string().optional(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('delay'),
        config: z.object({
            delay_duration: z.string(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('wait_for_condition'),
        config: z.object({
            condition: z.object({
                filter: z.any(), // type this stronger
                on_match: z.string(), // TODO: Can we type this more directly to an edge?
            }),
            delay_duration: z.string(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('message'),
        config: z.object({
            message: z.string(),
            channel: z.string(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('hog_function'),
        function_id: z.string(),
        config: z.object({
            args: z.record(z.any()),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('exit'),
        config: z.object({}),
    }),
])

export const HogFlowSchema = z.object({
    id: z.string(),
    team_id: z.number(),
    version: z.number(),
    name: z.string(),
    status: z.enum(['active', 'draft', 'archived']),
    trigger: z.object({
        type: z.literal('event'),
        filters: z.any(),
    }),
    trigger_masking: z
        .object({
            ttl: z.number(),
            hash: z.string(),
            threshold: z.number(),
        })
        .optional(),
    conversion: z
        .object({
            window_minutes: z.number(),
            filters: z.any(),
        })
        .optional(),
    exit_condition: z.enum([
        'exit_on_conversion',
        'exit_on_trigger_not_matched',
        'exit_on_trigger_not_matched_or_conversion',
        'exit_only_at_end',
    ]),
    edges: z.array(
        z.object({
            from: z.string(),
            to: z.string(),
            type: z.enum(['continue', 'branch']),
            index: z.number(),
        })
    ),
    actions: z.array(HogFlowActionSchema),
    abort_action: z.string().optional(),
})

export type HogFlow = z.infer<typeof HogFlowSchema>
export type HogFlowAction = HogFlow['actions'][number]
export type HogFlowEdge = HogFlow['edges'][number]
