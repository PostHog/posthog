import { z } from 'zod'

const _commonActionFields = {
    id: z.string(),
    name: z.string(),
    description: z.string(),
    on_error: z.enum(['continue', 'abort', 'complete', 'branch']).optional(),
    created_at: z.number(),
    updated_at: z.number(),
    filters: z.any(), // TODO: Correct to the right type
}

const HogFlowActionSchema = z.discriminatedUnion('type', [
    // Trigger
    z.object({
        ..._commonActionFields,
        type: z.literal('trigger'),
        config: z.object({
            filters: z.any(),
        }),
    }),
    // Branching
    z.object({
        ..._commonActionFields,
        type: z.literal('conditional_branch'),
        config: z.object({
            conditions: z.array(
                z.object({
                    filter: z.any(), // type this stronger
                })
            ),
            delay_duration: z.string().optional(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('random_cohort_branch'),
        config: z.object({
            cohorts: z.array(
                z.object({
                    percentage: z.number(),
                })
            ),
        }),
    }),

    // Time based
    z.object({
        ..._commonActionFields,
        type: z.literal('delay'),
        config: z.object({
            delay_duration: z.string(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('wait_until_condition'),
        config: z.object({
            condition: z.object({
                filter: z.any(), // type this stronger
            }),
            max_wait_duration: z.string(),
        }),
    }),

    z.object({
        ..._commonActionFields,
        type: z.literal('wait_until_time_window'),
        config: z.object({
            timezone: z.string(),
            // Date can be special values "weekday", "weekend" or a list of days of the week e.g. 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            date: z.union([
                z.literal('any'),
                z.literal('weekday'),
                z.literal('weekend'),
                z.array(z.enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])),
            ]),
            // time can be "any", or a time range [start, end]
            time: z.union([
                z.literal('any'),
                z.tuple([z.string(), z.string()]), // e.g. ['10:00', '11:00']
            ]),
        }),
    }),
    // Function
    z.object({
        ..._commonActionFields,
        type: z.literal('function'),
        config: z.object({
            function_id: z.string(),
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
            index: z.number().optional(),
        })
    ),
    actions: z.array(HogFlowActionSchema),
    abort_action: z.string().optional(),
})

export type HogFlow = z.infer<typeof HogFlowSchema>
export type HogFlowAction = HogFlow['actions'][number]
export type HogFlowEdge = HogFlow['edges'][number]
