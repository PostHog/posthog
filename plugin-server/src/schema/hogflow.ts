import { z } from 'zod'

import { CyclotronInputSchema } from './cyclotron'

const _commonActionFields = {
    id: z.string(),
    name: z.string(),
    description: z.string(),
    on_error: z.enum(['continue', 'abort']).optional(),
    created_at: z.number(),
    updated_at: z.number(),
    filters: z.any(), // TODO: Correct to the right type
}

const HogFlowTriggerSchema = z.discriminatedUnion('type', [
    z.object({
        type: z.literal('event'),
        filters: z.object({
            events: z.array(z.any()).optional(),
            properties: z.array(z.any()).optional(),
            actions: z.array(z.any()).optional(),
        }),
    }),
    z.object({
        type: z.literal('webhook'),
        template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(CyclotronInputSchema),
    }),
    z.object({
        type: z.literal('tracking_pixel'),
        template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(CyclotronInputSchema),
    }),
])

const HogFlowActionSchema = z.discriminatedUnion('type', [
    // Trigger
    z.object({
        ..._commonActionFields,
        type: z.literal('trigger'),
        config: HogFlowTriggerSchema,
        // A trigger's event filters are stored on the top-level Hogflow object
    }),
    // Branching
    z.object({
        ..._commonActionFields,
        type: z.literal('conditional_branch'),
        config: z.object({
            conditions: z.array(
                z.object({
                    filters: z.any(), // type this stronger
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
                filters: z.any(), // type this stronger
            }),
            max_wait_duration: z.string(),
        }),
    }),

    z.object({
        ..._commonActionFields,
        type: z.literal('wait_until_time_window'),
        config: z.object({
            timezone: z.string().nullable(),
            // Date can be special values "weekday", "weekend" or a list of days of the week e.g. 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
            day: z.union([
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

    // Native messages
    z.object({
        ..._commonActionFields,
        type: z.literal('function_email'),
        config: z.object({
            message_category_id: z.string().uuid().optional(),
            template_uuid: z.string().optional(), // May be used later to specify a specific template version
            template_id: z.literal('template-email'),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),

    // CDP functions
    z.object({
        ..._commonActionFields,
        type: z.literal('function'),
        config: z.object({
            template_uuid: z.string().uuid().optional(), // May be used later to specify a specific template version
            template_id: z.string(),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('function_sms'),
        config: z.object({
            message_category_id: z.string().uuid().optional(),
            template_uuid: z.string().uuid().optional(),
            template_id: z.literal('template-twilio'),
            inputs: z.record(CyclotronInputSchema),
        }),
    }),
    // Exit
    z.object({
        ..._commonActionFields,
        type: z.literal('exit'),
        config: z.object({
            reason: z.string().optional(),
        }),
    }),
])

const HogFlowEdgeSchema = z.object({
    from: z.string(),
    to: z.string(),
    type: z.enum(['continue', 'branch']),
    index: z.number().optional(),
})

export const HogFlowSchema = z.object({
    id: z.string(),
    team_id: z.number(),
    version: z.number(),
    name: z.string(),
    status: z.enum(['active', 'draft', 'archived']),
    trigger: HogFlowTriggerSchema,
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
    actions: z.array(HogFlowActionSchema),
    abort_action: z.string().optional(),
    edges: z.array(HogFlowEdgeSchema),
})

// NOTE: these are purposefully exported as interfaces to support kea typegen
export interface HogFlow extends z.infer<typeof HogFlowSchema> {}
export type HogFlowAction = z.infer<typeof HogFlowActionSchema> & Record<string, unknown>
export interface HogFlowEdge extends z.infer<typeof HogFlowEdgeSchema> {}
