import { z } from 'zod'

import { CyclotronInputMappingSchema, CyclotronInputSchema, CyclotronJobInputSchemaTypeSchema } from './cyclotron'

const _commonActionFields = {
    id: z.string(),
    name: z.string(),
    description: z.string(),
    on_error: z.enum(['continue', 'abort']).optional(),
    created_at: z.number(),
    updated_at: z.number(),
    filters: z.any(), // TODO: Correct to the right type
    output_variable: z // The Hogflow-level variable to store the output of this action into
        .union([
            z.object({
                key: z.string(),
                result_path: z.string().optional().nullable(), // The path within the action result to store, e.g. 'response.user.id'
                spread: z.boolean().optional().nullable(), // When true, spread object result into multiple variables as {key}_{property}
                label: z.string().optional().nullable(), // Display label for the auto-created workflow variable
            }),
            z.array(
                z.object({
                    key: z.string(),
                    result_path: z.string().optional().nullable(),
                    spread: z.boolean().optional().nullable(),
                    label: z.string().optional().nullable(),
                })
            ),
        ])
        .optional()
        .nullable(),
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
        template_uuid: z.string().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(z.string(), CyclotronInputSchema),
    }),
    z.object({
        type: z.literal('manual'),
        template_uuid: z.string().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(z.string(), CyclotronInputSchema),
    }),
    z.object({
        type: z.literal('tracking_pixel'),
        template_uuid: z.string().optional(), // May be used later to specify a specific template version
        template_id: z.string(),
        inputs: z.record(z.string(), CyclotronInputSchema),
    }),
    z.object({
        type: z.literal('schedule'),
    }),
    z.object({
        type: z.literal('batch'),
        filters: z.object({
            properties: z.array(z.any()),
        }),
    }),
    z.object({
        type: z.literal('data-warehouse-table'),
        // Dot-notated table name, matching the format produced by the Python CDPProducer
        // (see get_data_warehouse_table_name) so producer gating and trigger config use identical strings.
        table_name: z.string(),
        filters: z.object({
            // Row-property filters only - warehouse-triggered workflows are person-less ("row-scoped")
            properties: z.array(z.any()).optional(),
        }),
        // Optional row column used as the masking / dedup key in place of distinct_id
        key_property: z.string().optional(),
    }),
])

export const HogFlowActionSchema = z.discriminatedUnion('type', [
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
                    name: z.string().optional(), // Custom name for the condition
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
                    name: z.string().optional(), // Custom name for the cohort
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
                name: z.string().optional(), // Custom name for the condition
            }),
            events: z
                .array(
                    z.object({
                        filters: z.any(),
                        name: z.string().optional(),
                    })
                )
                .optional(),
            max_wait_duration: z.string(),
        }),
    }),

    z.object({
        ..._commonActionFields,
        type: z.literal('wait_until_time_window'),
        config: z.object({
            timezone: z.string().nullable(),
            // When true, use the person's $geoip_time_zone property for timezone
            use_person_timezone: z.boolean().optional(),
            // Fallback timezone when use_person_timezone is true but person has no timezone set
            fallback_timezone: z.string().nullable().optional(),
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

    // Agent task: kick off a PostHog Code task with a prompt and wait for it to finish.
    // Parks on entry (like wait_until_condition) and is woken by the $task_run_completed internal
    // event (terminal status carried as a property), with a status poll as backstop up to
    // max_wait_duration.
    z.object({
        ..._commonActionFields,
        type: z.literal('agent_task'),
        config: z.object({
            // The prompt sent to the task as its description (templated with workflow variables).
            prompt: z.string(),
            // Optional task title; the handler falls back to the action name when empty.
            title: z.string().optional(),
            // Target repository as `org/repo`; falls back to the team's default when empty.
            repository: z.string().optional(),
            // Whether the task should open a pull request when it finishes.
            create_pr: z.boolean().optional(),
            // How long to wait for the task before taking the timeout (continue) edge.
            max_wait_duration: z.string(),
        }),
    }),

    // Native messages
    z.object({
        ..._commonActionFields,
        type: z.literal('function_email'),
        config: z.object({
            message_category_id: z.string().optional(),
            message_category_type: z.enum(['marketing', 'transactional']).optional(),
            template_uuid: z.string().optional(), // May be used later to specify a specific template version
            template_id: z.literal('template-email'),
            inputs: z.record(z.string(), CyclotronInputSchema),
            mappings: z.array(CyclotronInputMappingSchema).optional(),
        }),
    }),

    // CDP functions
    z.object({
        ..._commonActionFields,
        type: z.literal('function'),
        config: z.object({
            template_uuid: z.string().optional(), // May be used later to specify a specific template version
            template_id: z.string(),
            inputs: z.record(z.string(), CyclotronInputSchema),
            mappings: z.array(CyclotronInputMappingSchema).optional(),
        }),
    }),
    z.object({
        ..._commonActionFields,
        type: z.literal('function_sms'),
        config: z.object({
            message_category_id: z.string().optional(),
            message_category_type: z.enum(['marketing', 'transactional']).optional(),
            template_uuid: z.string().optional(),
            template_id: z.literal('template-twilio'),
            inputs: z.record(z.string(), CyclotronInputSchema),
            mappings: z.array(CyclotronInputMappingSchema).optional(),
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
    // Optional masking config for the trigger, allows HogFlows to be rate limited per distinct ID or other property
    trigger_masking: z
        .object({
            ttl: z.number().nullable(),
            hash: z.string(),
            bytecode: z.array(z.union([z.string(), z.number()])),
            threshold: z.number().nullable(),
        })
        .optional()
        .nullable(),
    conversion: z
        .object({
            window_minutes: z.number().nullable(),
            filters: z.any(),
            bytecode: z.array(z.union([z.string(), z.number()])),
            events: z
                .array(
                    z.object({
                        filters: z.any(),
                        name: z.string().optional(),
                    })
                )
                .optional(),
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
    variables: z.array(CyclotronJobInputSchemaTypeSchema).optional().nullable(),
    billable_action_types: z.array(z.string()).optional().nullable(),
})

// NOTE: these are purposefully exported as interfaces to support kea typegen
export interface HogFlow extends z.infer<typeof HogFlowSchema> {}
export type HogFlowAction = z.infer<typeof HogFlowActionSchema> & Record<string, unknown>
export interface HogFlowEdge extends z.infer<typeof HogFlowEdgeSchema> {}
