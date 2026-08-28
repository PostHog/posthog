import { z } from 'zod'

import { CyclotronInputMappingSchema, CyclotronInputSchema, CyclotronJobInputSchemaTypeSchema } from './cyclotron'

export const HogFlowEmailSendingRateLimitSchema = z.object({
    count: z.number().int().positive(),
    period: z.enum(['minute', 'hour']),
})

export type HogFlowEmailSendingRateLimit = z.infer<typeof HogFlowEmailSendingRateLimitSchema>

const HogFlowOutputVariableSchema = z.object({
    key: z.string(),
    result_path: z.string().optional().nullable(), // The path within the action result to store, e.g. 'response.user.id'
    spread: z.boolean().optional().nullable(), // When true, spread object result into multiple variables as {key}_{property}
    label: z.string().optional().nullable(), // Display label for the auto-created workflow variable
})

// Rows written before the API coerced bare key strings — normalize at read so one legacy value
// can't make the whole flow row unparseable. The annotated return type keeps the union's output
// type identical to the object schema's, so downstream field access still narrows.
const legacyStringOutputVariable = z.string().transform((key): z.infer<typeof HogFlowOutputVariableSchema> => ({ key }))

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
            HogFlowOutputVariableSchema,
            z.array(z.union([HogFlowOutputVariableSchema, legacyStringOutputVariable])),
            legacyStringOutputVariable,
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
            // 'accounts' fans out one run per customer analytics account instead of per person
            audience_type: z.enum(['persons', 'accounts']).optional(),
            properties: z.array(z.any()),
            filter_test_accounts: z.boolean().optional(),
            tag_names: z.array(z.string()).optional(),
            assigned_to_user_ids: z.array(z.number()).optional(),
            all_roles_unassigned: z.boolean().optional(),
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
    z.object({
        type: z.literal('slack-message'),
        filters: z.object({
            // Message-property filters only. Channel is one of these rather than a field of its own,
            // so it composes with poster and text conditions instead of being matched separately.
            properties: z.array(z.any()).optional(),
        }),
    }),
    z.object({
        type: z.literal('data-warehouse-view'),
        // The materialized view's own name, which is also the name it is queryable by in HogQL.
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
        // Two ways to say when to continue, exactly one of which is set. `delay_duration` waits a fixed
        // span from when the step starts. `delay_until` waits for an instant carried by the person or the
        // event, which a fixed duration cannot express (e.g. a per-person trial expiry).
        config: z.object({
            delay_duration: z.string().optional(),
            delay_until: z
                .object({
                    // HogQL evaluating to a datetime: an ISO string, a HogDateTime, or unix seconds.
                    expression: z.string(),
                    // Signed offset applied to that instant, e.g. '-1d' for "one day before". Kept separate
                    // from the expression so the builder can offer a property picker instead of arithmetic.
                    offset: z.string().optional(),
                    // Which zone a date with no offset of its own is read in, the same three fields
                    // wait_until_time_window uses. A stored '2026-03-01' means midnight where the customer
                    // lives, not midnight UTC.
                    timezone: z.string().nullish(),
                    use_person_timezone: z.boolean().optional(),
                    fallback_timezone: z.string().nullish(),
                    bytecode: z.any().optional(),
                    bytecode_error: z.string().optional(),
                })
                .optional(),
            // How long past the step's start the wait may run, so a far-future or malformed instant cannot
            // park a run indefinitely. Applies to delay_until only.
            max_delay_duration: z.string().optional(),
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

    // Native messages
    z.object({
        ..._commonActionFields,
        type: z.literal('function_email'),
        config: z.object({
            message_category_id: z.string().optional(),
            message_category_type: z.enum(['marketing', 'transactional']).optional(),
            // When false, no open pixel is injected, links are not rewritten, and the send uses the
            // untracked SES configuration set. Absent/true means tracked (existing behavior).
            tracking_enabled: z.boolean().optional(),
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
    z.object({
        ..._commonActionFields,
        type: z.literal('function_push'),
        config: z.object({
            message_category_id: z.string().uuid().optional(),
            message_category_type: z.enum(['marketing', 'transactional']).optional(),
            template_uuid: z.string().uuid().optional(),
            template_id: z.literal('template-native-push'),
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
    // User-configured email pacing for deliverability. The email worker holds this flow's sends
    // under the limit by rescheduling over-limit sends, never dropping them.
    email_sending_rate_limit: HogFlowEmailSendingRateLimitSchema.optional().nullable(),
    actions: z.array(HogFlowActionSchema),
    // Secret function inputs, split out of `actions` and stored Fernet-encrypted at rest, keyed by
    // action id then input key. Decrypted by the manager and merged back into `action.config.inputs`
    // before execution; never present on the plaintext `actions` blob.
    encrypted_inputs: z.record(z.string(), z.record(z.string(), CyclotronInputSchema)).optional().nullable(),
    abort_action: z.string().optional(),
    edges: z.array(HogFlowEdgeSchema),
    variables: z.array(CyclotronJobInputSchemaTypeSchema).optional().nullable(),
    billable_action_types: z.array(z.string()).optional().nullable(),
    // Skip-forward map for deleted steps ({deleted_action_id: surviving_action_id}), maintained by
    // the API on live graph edits. Values always reference actions present in this flow's `actions`.
    action_redirects: z.record(z.string(), z.string()).optional().nullable(),
    // Selected by the worker (HOG_FLOW_FIELDS); pg returns timestamptz as a Date, fixtures use
    // epoch millis. Used to distinguish live edits from malformed-from-birth graphs.
    updated_at: z.union([z.number(), z.string(), z.date()]).optional(),
})

export type RowScopedTrigger = Extract<HogFlow['trigger'], { type: 'data-warehouse-table' | 'data-warehouse-view' }>

/**
 * A warehouse-row trigger produces one run per row, with the row's columns under
 * `event.properties` and no person attached.
 */
export function isRowScopedTrigger(trigger: HogFlow['trigger']): trigger is RowScopedTrigger {
    return trigger?.type === 'data-warehouse-table' || trigger?.type === 'data-warehouse-view'
}

// NOTE: these are purposefully exported as interfaces to support kea typegen
export interface HogFlow extends z.infer<typeof HogFlowSchema> {}
export type HogFlowAction = z.infer<typeof HogFlowActionSchema> & Record<string, unknown>
export interface HogFlowEdge extends z.infer<typeof HogFlowEdgeSchema> {}
