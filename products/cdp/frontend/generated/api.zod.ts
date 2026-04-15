/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const hogFunctionTemplatesListResponseResultsItemNameMax = 400

export const hogFunctionTemplatesListResponseResultsItemCodeLanguageMax = 20

export const hogFunctionTemplatesListResponseResultsItemTypeMax = 50

export const hogFunctionTemplatesListResponseResultsItemStatusMax = 20

export const HogFunctionTemplatesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(hogFunctionTemplatesListResponseResultsItemStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        use_all_events_by_default: zod
                            .boolean()
                            .nullish()
                            .describe(
                                'Whether this mapping should match all events by default, hiding the event filter UI.'
                            ),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
    ),
})

export const hogFunctionTemplatesRetrieveResponseNameMax = 400

export const hogFunctionTemplatesRetrieveResponseCodeLanguageMax = 20

export const hogFunctionTemplatesRetrieveResponseTypeMax = 50

export const hogFunctionTemplatesRetrieveResponseStatusMax = 20

export const HogFunctionTemplatesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
    name: zod.string().max(hogFunctionTemplatesRetrieveResponseNameMax).describe('Display name of the template.'),
    description: zod.string().nullish().describe('What this template does.'),
    code: zod.string().describe('Source code of the template.'),
    code_language: zod
        .string()
        .max(hogFunctionTemplatesRetrieveResponseCodeLanguageMax)
        .optional()
        .describe("Programming language: 'hog' or 'javascript'."),
    inputs_schema: zod
        .unknown()
        .describe('Schema defining configurable inputs for functions created from this template.'),
    type: zod
        .string()
        .max(hogFunctionTemplatesRetrieveResponseTypeMax)
        .describe('Function type this template creates.'),
    status: zod
        .string()
        .max(hogFunctionTemplatesRetrieveResponseStatusMax)
        .optional()
        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
    free: zod.boolean().optional().describe('Whether available on free plans.'),
    icon_url: zod.string().nullish().describe("URL for the template's icon."),
    filters: zod.unknown().nullish().describe('Default event filters.'),
    masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
    mapping_templates: zod
        .array(
            zod.object({
                name: zod.string().describe('Name of this mapping template.'),
                include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
                use_all_events_by_default: zod
                    .boolean()
                    .nullish()
                    .describe('Whether this mapping should match all events by default, hiding the event filter UI.'),
                filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                inputs_schema: zod
                    .unknown()
                    .nullish()
                    .describe('Additional input schema fields specific to this mapping.'),
            })
        )
        .nullish()
        .describe('Pre-defined mapping configurations for destination templates.'),
})

export const hogFunctionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const hogFunctionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const hogFunctionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const hogFunctionsListResponseResultsItemCreatedByOneEmailMax = 254

export const hogFunctionsListResponseResultsItemTemplateOneNameMax = 400

export const hogFunctionsListResponseResultsItemTemplateOneCodeLanguageMax = 20

export const hogFunctionsListResponseResultsItemTemplateOneTypeMax = 50

export const hogFunctionsListResponseResultsItemTemplateOneStatusMax = 20

export const HogFunctionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            type: zod.string().nullable(),
            name: zod.string().nullable(),
            description: zod.string(),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(hogFunctionsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(hogFunctionsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(hogFunctionsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(hogFunctionsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}),
            enabled: zod.boolean(),
            hog: zod.string(),
            filters: zod.unknown().nullable(),
            icon_url: zod.string().nullable(),
            template: zod.object({
                id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                name: zod
                    .string()
                    .max(hogFunctionsListResponseResultsItemTemplateOneNameMax)
                    .describe('Display name of the template.'),
                description: zod.string().nullish().describe('What this template does.'),
                code: zod.string().describe('Source code of the template.'),
                code_language: zod
                    .string()
                    .max(hogFunctionsListResponseResultsItemTemplateOneCodeLanguageMax)
                    .optional()
                    .describe("Programming language: 'hog' or 'javascript'."),
                inputs_schema: zod
                    .unknown()
                    .describe('Schema defining configurable inputs for functions created from this template.'),
                type: zod
                    .string()
                    .max(hogFunctionsListResponseResultsItemTemplateOneTypeMax)
                    .describe('Function type this template creates.'),
                status: zod
                    .string()
                    .max(hogFunctionsListResponseResultsItemTemplateOneStatusMax)
                    .optional()
                    .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                free: zod.boolean().optional().describe('Whether available on free plans.'),
                icon_url: zod.string().nullish().describe("URL for the template's icon."),
                filters: zod.unknown().nullish().describe('Default event filters.'),
                masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                mapping_templates: zod
                    .array(
                        zod.object({
                            name: zod.string().describe('Name of this mapping template.'),
                            include_by_default: zod
                                .boolean()
                                .nullish()
                                .describe('Whether this mapping is enabled by default.'),
                            use_all_events_by_default: zod
                                .boolean()
                                .nullish()
                                .describe(
                                    'Whether this mapping should match all events by default, hiding the event filter UI.'
                                ),
                            filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                            inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                            inputs_schema: zod
                                .unknown()
                                .nullish()
                                .describe('Additional input schema fields specific to this mapping.'),
                        })
                    )
                    .nullish()
                    .describe('Pre-defined mapping configurations for destination templates.'),
            }),
            status: zod
                .object({
                    state: zod
                        .union([
                            zod.literal(0),
                            zod.literal(1),
                            zod.literal(2),
                            zod.literal(3),
                            zod.literal(11),
                            zod.literal(12),
                        ])
                        .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
                    tokens: zod.number(),
                })
                .nullable(),
            execution_order: zod.number().nullable(),
        })
    ),
})

export const hogFunctionsCreateBodyNameMax = 400

export const hogFunctionsCreateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsCreateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsCreateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsCreateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsCreateBodyMaskingOneTtlMin = 60
export const hogFunctionsCreateBodyMaskingOneTtlMax = 86400

export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsCreateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsCreateBodyTemplateIdMax = 400

export const hogFunctionsCreateBodyExecutionOrderMin = 0
export const hogFunctionsCreateBodyExecutionOrderMax = 32767

export const HogFunctionsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsCreateBodyNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsCreateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsCreateBodyMaskingOneTtlMin)
                .max(hogFunctionsCreateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsCreateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsCreateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsCreateBodyExecutionOrderMin)
        .max(hogFunctionsCreateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
})

export const hogFunctionsRetrieveResponseNameMax = 400

export const hogFunctionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsRetrieveResponseCreatedByOneLastNameMax = 150

export const hogFunctionsRetrieveResponseCreatedByOneEmailMax = 254

export const hogFunctionsRetrieveResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsRetrieveResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsRetrieveResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsRetrieveResponseFiltersOneSourceDefault = `events`
export const hogFunctionsRetrieveResponseMaskingOneTtlMin = 60
export const hogFunctionsRetrieveResponseMaskingOneTtlMax = 86400

export const hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsRetrieveResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsRetrieveResponseTemplateOneNameMax = 400

export const hogFunctionsRetrieveResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsRetrieveResponseTemplateOneTypeMax = 50

export const hogFunctionsRetrieveResponseTemplateOneStatusMax = 20

export const hogFunctionsRetrieveResponseTemplateIdMax = 400

export const hogFunctionsRetrieveResponseExecutionOrderMin = 0
export const hogFunctionsRetrieveResponseExecutionOrderMax = 32767

export const HogFunctionsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsRetrieveResponseNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFunctionsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFunctionsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFunctionsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFunctionsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    bytecode: zod.unknown().nullable(),
    transpiled: zod.string().nullable(),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsRetrieveResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsRetrieveResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsRetrieveResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsRetrieveResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsRetrieveResponseMaskingOneTtlMin)
                .max(hogFunctionsRetrieveResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsRetrieveResponseMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsRetrieveResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod.object({
        id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
        name: zod
            .string()
            .max(hogFunctionsRetrieveResponseTemplateOneNameMax)
            .describe('Display name of the template.'),
        description: zod.string().nullish().describe('What this template does.'),
        code: zod.string().describe('Source code of the template.'),
        code_language: zod
            .string()
            .max(hogFunctionsRetrieveResponseTemplateOneCodeLanguageMax)
            .optional()
            .describe("Programming language: 'hog' or 'javascript'."),
        inputs_schema: zod
            .unknown()
            .describe('Schema defining configurable inputs for functions created from this template.'),
        type: zod
            .string()
            .max(hogFunctionsRetrieveResponseTemplateOneTypeMax)
            .describe('Function type this template creates.'),
        status: zod
            .string()
            .max(hogFunctionsRetrieveResponseTemplateOneStatusMax)
            .optional()
            .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
        category: zod.unknown().optional().describe('Category tags for organizing templates.'),
        free: zod.boolean().optional().describe('Whether available on free plans.'),
        icon_url: zod.string().nullish().describe("URL for the template's icon."),
        filters: zod.unknown().nullish().describe('Default event filters.'),
        masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
        mapping_templates: zod
            .array(
                zod.object({
                    name: zod.string().describe('Name of this mapping template.'),
                    include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
                    use_all_events_by_default: zod
                        .boolean()
                        .nullish()
                        .describe(
                            'Whether this mapping should match all events by default, hiding the event filter UI.'
                        ),
                    filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                    inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                    inputs_schema: zod
                        .unknown()
                        .nullish()
                        .describe('Additional input schema fields specific to this mapping.'),
                })
            )
            .nullish()
            .describe('Pre-defined mapping configurations for destination templates.'),
    }),
    template_id: zod
        .string()
        .max(hogFunctionsRetrieveResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    status: zod
        .object({
            state: zod
                .union([
                    zod.literal(0),
                    zod.literal(1),
                    zod.literal(2),
                    zod.literal(3),
                    zod.literal(11),
                    zod.literal(12),
                ])
                .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
            tokens: zod.number(),
        })
        .nullable(),
    execution_order: zod
        .number()
        .min(hogFunctionsRetrieveResponseExecutionOrderMin)
        .max(hogFunctionsRetrieveResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
    batch_export_id: zod.uuid().nullable(),
})

export const hogFunctionsUpdateBodyNameMax = 400

export const hogFunctionsUpdateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsUpdateBodyMaskingOneTtlMin = 60
export const hogFunctionsUpdateBodyMaskingOneTtlMax = 86400

export const hogFunctionsUpdateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsUpdateBodyTemplateIdMax = 400

export const hogFunctionsUpdateBodyExecutionOrderMin = 0
export const hogFunctionsUpdateBodyExecutionOrderMax = 32767

export const HogFunctionsUpdateBody = /* @__PURE__ */ zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsUpdateBodyNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsUpdateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsUpdateBodyMaskingOneTtlMin)
                .max(hogFunctionsUpdateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsUpdateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsUpdateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsUpdateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsUpdateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsUpdateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsUpdateBodyExecutionOrderMin)
        .max(hogFunctionsUpdateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
})

export const hogFunctionsUpdateResponseNameMax = 400

export const hogFunctionsUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsUpdateResponseCreatedByOneLastNameMax = 150

export const hogFunctionsUpdateResponseCreatedByOneEmailMax = 254

export const hogFunctionsUpdateResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateResponseFiltersOneSourceDefault = `events`
export const hogFunctionsUpdateResponseMaskingOneTtlMin = 60
export const hogFunctionsUpdateResponseMaskingOneTtlMax = 86400

export const hogFunctionsUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsUpdateResponseTemplateOneNameMax = 400

export const hogFunctionsUpdateResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsUpdateResponseTemplateOneTypeMax = 50

export const hogFunctionsUpdateResponseTemplateOneStatusMax = 20

export const hogFunctionsUpdateResponseTemplateIdMax = 400

export const hogFunctionsUpdateResponseExecutionOrderMin = 0
export const hogFunctionsUpdateResponseExecutionOrderMax = 32767

export const HogFunctionsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsUpdateResponseNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFunctionsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFunctionsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFunctionsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFunctionsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    bytecode: zod.unknown().nullable(),
    transpiled: zod.string().nullable(),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsUpdateResponseMaskingOneTtlMin)
                .max(hogFunctionsUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsUpdateResponseMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsUpdateResponseMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsUpdateResponseMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod.object({
        id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
        name: zod.string().max(hogFunctionsUpdateResponseTemplateOneNameMax).describe('Display name of the template.'),
        description: zod.string().nullish().describe('What this template does.'),
        code: zod.string().describe('Source code of the template.'),
        code_language: zod
            .string()
            .max(hogFunctionsUpdateResponseTemplateOneCodeLanguageMax)
            .optional()
            .describe("Programming language: 'hog' or 'javascript'."),
        inputs_schema: zod
            .unknown()
            .describe('Schema defining configurable inputs for functions created from this template.'),
        type: zod
            .string()
            .max(hogFunctionsUpdateResponseTemplateOneTypeMax)
            .describe('Function type this template creates.'),
        status: zod
            .string()
            .max(hogFunctionsUpdateResponseTemplateOneStatusMax)
            .optional()
            .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
        category: zod.unknown().optional().describe('Category tags for organizing templates.'),
        free: zod.boolean().optional().describe('Whether available on free plans.'),
        icon_url: zod.string().nullish().describe("URL for the template's icon."),
        filters: zod.unknown().nullish().describe('Default event filters.'),
        masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
        mapping_templates: zod
            .array(
                zod.object({
                    name: zod.string().describe('Name of this mapping template.'),
                    include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
                    use_all_events_by_default: zod
                        .boolean()
                        .nullish()
                        .describe(
                            'Whether this mapping should match all events by default, hiding the event filter UI.'
                        ),
                    filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                    inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                    inputs_schema: zod
                        .unknown()
                        .nullish()
                        .describe('Additional input schema fields specific to this mapping.'),
                })
            )
            .nullish()
            .describe('Pre-defined mapping configurations for destination templates.'),
    }),
    template_id: zod
        .string()
        .max(hogFunctionsUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    status: zod
        .object({
            state: zod
                .union([
                    zod.literal(0),
                    zod.literal(1),
                    zod.literal(2),
                    zod.literal(3),
                    zod.literal(11),
                    zod.literal(12),
                ])
                .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
            tokens: zod.number(),
        })
        .nullable(),
    execution_order: zod
        .number()
        .min(hogFunctionsUpdateResponseExecutionOrderMin)
        .max(hogFunctionsUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
    batch_export_id: zod.uuid().nullable(),
})

export const hogFunctionsPartialUpdateBodyNameMax = 400

export const hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsPartialUpdateBodyMaskingOneTtlMin = 60
export const hogFunctionsPartialUpdateBodyMaskingOneTtlMax = 86400

export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsPartialUpdateBodyTemplateIdMax = 400

export const hogFunctionsPartialUpdateBodyExecutionOrderMin = 0
export const hogFunctionsPartialUpdateBodyExecutionOrderMax = 32767

export const HogFunctionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsPartialUpdateBodyNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsPartialUpdateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsPartialUpdateBodyMaskingOneTtlMin)
                .max(hogFunctionsPartialUpdateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsPartialUpdateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsPartialUpdateBodyExecutionOrderMin)
        .max(hogFunctionsPartialUpdateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
})

export const hogFunctionsPartialUpdateResponseNameMax = 400

export const hogFunctionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFunctionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFunctionsPartialUpdateResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateResponseFiltersOneSourceDefault = `events`
export const hogFunctionsPartialUpdateResponseMaskingOneTtlMin = 60
export const hogFunctionsPartialUpdateResponseMaskingOneTtlMax = 86400

export const hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsPartialUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsPartialUpdateResponseTemplateOneNameMax = 400

export const hogFunctionsPartialUpdateResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsPartialUpdateResponseTemplateOneTypeMax = 50

export const hogFunctionsPartialUpdateResponseTemplateOneStatusMax = 20

export const hogFunctionsPartialUpdateResponseTemplateIdMax = 400

export const hogFunctionsPartialUpdateResponseExecutionOrderMin = 0
export const hogFunctionsPartialUpdateResponseExecutionOrderMax = 32767

export const HogFunctionsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsPartialUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFunctionsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFunctionsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFunctionsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFunctionsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    bytecode: zod.unknown().nullable(),
    transpiled: zod.string().nullable(),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsPartialUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsPartialUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsPartialUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsPartialUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsPartialUpdateResponseMaskingOneTtlMin)
                .max(hogFunctionsPartialUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsPartialUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod.object({
        id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
        name: zod
            .string()
            .max(hogFunctionsPartialUpdateResponseTemplateOneNameMax)
            .describe('Display name of the template.'),
        description: zod.string().nullish().describe('What this template does.'),
        code: zod.string().describe('Source code of the template.'),
        code_language: zod
            .string()
            .max(hogFunctionsPartialUpdateResponseTemplateOneCodeLanguageMax)
            .optional()
            .describe("Programming language: 'hog' or 'javascript'."),
        inputs_schema: zod
            .unknown()
            .describe('Schema defining configurable inputs for functions created from this template.'),
        type: zod
            .string()
            .max(hogFunctionsPartialUpdateResponseTemplateOneTypeMax)
            .describe('Function type this template creates.'),
        status: zod
            .string()
            .max(hogFunctionsPartialUpdateResponseTemplateOneStatusMax)
            .optional()
            .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
        category: zod.unknown().optional().describe('Category tags for organizing templates.'),
        free: zod.boolean().optional().describe('Whether available on free plans.'),
        icon_url: zod.string().nullish().describe("URL for the template's icon."),
        filters: zod.unknown().nullish().describe('Default event filters.'),
        masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
        mapping_templates: zod
            .array(
                zod.object({
                    name: zod.string().describe('Name of this mapping template.'),
                    include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
                    use_all_events_by_default: zod
                        .boolean()
                        .nullish()
                        .describe(
                            'Whether this mapping should match all events by default, hiding the event filter UI.'
                        ),
                    filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                    inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                    inputs_schema: zod
                        .unknown()
                        .nullish()
                        .describe('Additional input schema fields specific to this mapping.'),
                })
            )
            .nullish()
            .describe('Pre-defined mapping configurations for destination templates.'),
    }),
    template_id: zod
        .string()
        .max(hogFunctionsPartialUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    status: zod
        .object({
            state: zod
                .union([
                    zod.literal(0),
                    zod.literal(1),
                    zod.literal(2),
                    zod.literal(3),
                    zod.literal(11),
                    zod.literal(12),
                ])
                .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
            tokens: zod.number(),
        })
        .nullable(),
    execution_order: zod
        .number()
        .min(hogFunctionsPartialUpdateResponseExecutionOrderMin)
        .max(hogFunctionsPartialUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
    batch_export_id: zod.uuid().nullable(),
})

export const hogFunctionsEnableBackfillsCreateBodyNameMax = 400

export const hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemRequiredDefault = false
export const hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemSecretDefault = false
export const hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemHiddenDefault = false
export const hogFunctionsEnableBackfillsCreateBodyFiltersOneSourceDefault = `events`
export const hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMin = 60
export const hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMax = 86400

export const hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsEnableBackfillsCreateBodyMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsEnableBackfillsCreateBodyTemplateIdMax = 400

export const hogFunctionsEnableBackfillsCreateBodyExecutionOrderMin = 0
export const hogFunctionsEnableBackfillsCreateBodyExecutionOrderMax = 32767

export const HogFunctionsEnableBackfillsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsEnableBackfillsCreateBodyNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsEnableBackfillsCreateBodyInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsEnableBackfillsCreateBodyFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMin)
                .max(hogFunctionsEnableBackfillsCreateBodyMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    hogFunctionsEnableBackfillsCreateBodyMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsEnableBackfillsCreateBodyMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsEnableBackfillsCreateBodyTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsEnableBackfillsCreateBodyExecutionOrderMin)
        .max(hogFunctionsEnableBackfillsCreateBodyExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
})

export const hogFunctionsInvocationsCreateBodyConfigurationOneNameMax = 400

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax = 200

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax = 150

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax = 150

export const hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax = 254

export const hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneFiltersOneSourceDefault = `events`
export const hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMin = 60
export const hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMax = 86400

export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneNameMax = 400

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneCodeLanguageMax = 20

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneTypeMax = 50

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneStatusMax = 20

export const hogFunctionsInvocationsCreateBodyConfigurationOneTemplateIdMax = 400

export const hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin = 0
export const hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax = 32767

export const hogFunctionsInvocationsCreateBodyMockAsyncFunctionsDefault = true

export const HogFunctionsInvocationsCreateBody = /* @__PURE__ */ zod.object({
    configuration: zod
        .object({
            id: zod.uuid(),
            type: zod
                .union([
                    zod
                        .enum([
                            'destination',
                            'site_destination',
                            'internal_destination',
                            'source_webhook',
                            'warehouse_source_webhook',
                            'site_app',
                            'transformation',
                        ])
                        .describe(
                            '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                        ),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            name: zod
                .string()
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneNameMax)
                .nullish()
                .describe('Display name for the function.'),
            description: zod.string().optional().describe('Human-readable description of what this function does.'),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(hogFunctionsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            bytecode: zod.unknown().nullable(),
            transpiled: zod.string().nullable(),
            inputs_schema: zod
                .array(
                    zod.object({
                        type: zod
                            .enum([
                                'string',
                                'number',
                                'boolean',
                                'dictionary',
                                'choice',
                                'json',
                                'integration',
                                'integration_field',
                                'email',
                                'native_email',
                                'posthog_assignee',
                                'posthog_ticket_tags',
                            ])
                            .describe(
                                '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                            ),
                        key: zod.string(),
                        label: zod.string().optional(),
                        choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        required: zod
                            .boolean()
                            .default(hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemRequiredDefault),
                        default: zod.unknown().optional(),
                        secret: zod
                            .boolean()
                            .default(hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemSecretDefault),
                        hidden: zod
                            .boolean()
                            .default(hogFunctionsInvocationsCreateBodyConfigurationOneInputsSchemaItemHiddenDefault),
                        description: zod.string().optional(),
                        integration: zod.string().optional(),
                        integration_key: zod.string().optional(),
                        requires_field: zod.string().optional(),
                        integration_field: zod.string().optional(),
                        requiredScopes: zod.string().optional(),
                        templating: zod
                            .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                            .optional()
                            .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                    })
                )
                .optional()
                .describe('Schema defining the configurable input parameters for this function.'),
            inputs: zod
                .record(
                    zod.string(),
                    zod.object({
                        value: zod.unknown().optional(),
                        templating: zod
                            .enum(['hog', 'liquid'])
                            .optional()
                            .describe('* `hog` - hog\n* `liquid` - liquid'),
                        bytecode: zod.array(zod.unknown()),
                        order: zod.number(),
                        transpiled: zod.unknown(),
                    })
                )
                .optional()
                .describe('Values for each input defined in inputs_schema.'),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFunctionsInvocationsCreateBodyConfigurationOneFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .optional()
                .describe('Event filters that control which events trigger this function.'),
            masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMin)
                        .max(hogFunctionsInvocationsCreateBodyConfigurationOneMaskingOneTtlMax)
                        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash expression. Auto-generated.'),
                })
                .nullish()
                .describe('PII masking configuration with TTL, threshold, and hash expression.'),
            mappings: zod
                .array(
                    zod.object({
                        name: zod.string().optional(),
                        inputs_schema: zod
                            .array(
                                zod.object({
                                    type: zod
                                        .enum([
                                            'string',
                                            'number',
                                            'boolean',
                                            'dictionary',
                                            'choice',
                                            'json',
                                            'integration',
                                            'integration_field',
                                            'email',
                                            'native_email',
                                            'posthog_assignee',
                                            'posthog_ticket_tags',
                                        ])
                                        .describe(
                                            '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                        ),
                                    key: zod.string(),
                                    label: zod.string().optional(),
                                    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    required: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemRequiredDefault
                                        ),
                                    default: zod.unknown().optional(),
                                    secret: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemSecretDefault
                                        ),
                                    hidden: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemInputsSchemaItemHiddenDefault
                                        ),
                                    description: zod.string().optional(),
                                    integration: zod.string().optional(),
                                    integration_key: zod.string().optional(),
                                    requires_field: zod.string().optional(),
                                    integration_field: zod.string().optional(),
                                    requiredScopes: zod.string().optional(),
                                    templating: zod
                                        .union([
                                            zod.literal(true),
                                            zod.literal(false),
                                            zod.literal('hog'),
                                            zod.literal('liquid'),
                                        ])
                                        .optional()
                                        .describe(
                                            '* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'
                                        ),
                                })
                            )
                            .optional(),
                        inputs: zod
                            .record(
                                zod.string(),
                                zod.object({
                                    value: zod.unknown().optional(),
                                    templating: zod
                                        .enum(['hog', 'liquid'])
                                        .optional()
                                        .describe('* `hog` - hog\n* `liquid` - liquid'),
                                    bytecode: zod.array(zod.unknown()),
                                    order: zod.number(),
                                    transpiled: zod.unknown(),
                                })
                            )
                            .optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(
                                        hogFunctionsInvocationsCreateBodyConfigurationOneMappingsItemFiltersSourceDefault
                                    ),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                bytecode: zod.unknown().nullish(),
                                transpiled: zod.unknown().optional(),
                                filter_test_accounts: zod.boolean().optional(),
                                bytecode_error: zod.string().optional(),
                            })
                            .optional(),
                    })
                )
                .nullish()
                .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
            icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
            template: zod.object({
                id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                name: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneNameMax)
                    .describe('Display name of the template.'),
                description: zod.string().nullish().describe('What this template does.'),
                code: zod.string().describe('Source code of the template.'),
                code_language: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneCodeLanguageMax)
                    .optional()
                    .describe("Programming language: 'hog' or 'javascript'."),
                inputs_schema: zod
                    .unknown()
                    .describe('Schema defining configurable inputs for functions created from this template.'),
                type: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneTypeMax)
                    .describe('Function type this template creates.'),
                status: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateOneStatusMax)
                    .optional()
                    .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                free: zod.boolean().optional().describe('Whether available on free plans.'),
                icon_url: zod.string().nullish().describe("URL for the template's icon."),
                filters: zod.unknown().nullish().describe('Default event filters.'),
                masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                mapping_templates: zod
                    .array(
                        zod.object({
                            name: zod.string().describe('Name of this mapping template.'),
                            include_by_default: zod
                                .boolean()
                                .nullish()
                                .describe('Whether this mapping is enabled by default.'),
                            use_all_events_by_default: zod
                                .boolean()
                                .nullish()
                                .describe(
                                    'Whether this mapping should match all events by default, hiding the event filter UI.'
                                ),
                            filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                            inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                            inputs_schema: zod
                                .unknown()
                                .nullish()
                                .describe('Additional input schema fields specific to this mapping.'),
                        })
                    )
                    .nullish()
                    .describe('Pre-defined mapping configurations for destination templates.'),
            }),
            template_id: zod
                .string()
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneTemplateIdMax)
                .nullish()
                .describe('ID of the template to create this function from.'),
            status: zod
                .object({
                    state: zod
                        .union([
                            zod.literal(0),
                            zod.literal(1),
                            zod.literal(2),
                            zod.literal(3),
                            zod.literal(11),
                            zod.literal(12),
                        ])
                        .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
                    tokens: zod.number(),
                })
                .nullable(),
            execution_order: zod
                .number()
                .min(hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMin)
                .max(hogFunctionsInvocationsCreateBodyConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
            _create_in_folder: zod.string().optional(),
            batch_export_id: zod.uuid().nullable(),
        })
        .describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFunctionsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

export const hogFunctionsInvocationsCreateResponseConfigurationOneNameMax = 400

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneDistinctIdMax = 200

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneFirstNameMax = 150

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneLastNameMax = 150

export const hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneEmailMax = 254

export const hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneFiltersOneSourceDefault = `events`
export const hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMin = 60
export const hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMax = 86400

export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneNameMax = 400

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneCodeLanguageMax = 20

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneTypeMax = 50

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneStatusMax = 20

export const hogFunctionsInvocationsCreateResponseConfigurationOneTemplateIdMax = 400

export const hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMin = 0
export const hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMax = 32767

export const hogFunctionsInvocationsCreateResponseMockAsyncFunctionsDefault = true

export const HogFunctionsInvocationsCreateResponse = /* @__PURE__ */ zod.object({
    configuration: zod
        .object({
            id: zod.uuid(),
            type: zod
                .union([
                    zod
                        .enum([
                            'destination',
                            'site_destination',
                            'internal_destination',
                            'source_webhook',
                            'warehouse_source_webhook',
                            'site_app',
                            'transformation',
                        ])
                        .describe(
                            '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                        ),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            name: zod
                .string()
                .max(hogFunctionsInvocationsCreateResponseConfigurationOneNameMax)
                .nullish()
                .describe('Display name for the function.'),
            description: zod.string().optional().describe('Human-readable description of what this function does.'),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(hogFunctionsInvocationsCreateResponseConfigurationOneCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}),
            enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
            deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
            hog: zod
                .string()
                .optional()
                .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
            bytecode: zod.unknown().nullable(),
            transpiled: zod.string().nullable(),
            inputs_schema: zod
                .array(
                    zod.object({
                        type: zod
                            .enum([
                                'string',
                                'number',
                                'boolean',
                                'dictionary',
                                'choice',
                                'json',
                                'integration',
                                'integration_field',
                                'email',
                                'native_email',
                                'posthog_assignee',
                                'posthog_ticket_tags',
                            ])
                            .describe(
                                '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                            ),
                        key: zod.string(),
                        label: zod.string().optional(),
                        choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        required: zod
                            .boolean()
                            .default(
                                hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemRequiredDefault
                            ),
                        default: zod.unknown().optional(),
                        secret: zod
                            .boolean()
                            .default(
                                hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemSecretDefault
                            ),
                        hidden: zod
                            .boolean()
                            .default(
                                hogFunctionsInvocationsCreateResponseConfigurationOneInputsSchemaItemHiddenDefault
                            ),
                        description: zod.string().optional(),
                        integration: zod.string().optional(),
                        integration_key: zod.string().optional(),
                        requires_field: zod.string().optional(),
                        integration_field: zod.string().optional(),
                        requiredScopes: zod.string().optional(),
                        templating: zod
                            .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                            .optional()
                            .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                    })
                )
                .optional()
                .describe('Schema defining the configurable input parameters for this function.'),
            inputs: zod
                .record(
                    zod.string(),
                    zod.object({
                        value: zod.unknown().optional(),
                        templating: zod
                            .enum(['hog', 'liquid'])
                            .optional()
                            .describe('* `hog` - hog\n* `liquid` - liquid'),
                        bytecode: zod.array(zod.unknown()),
                        order: zod.number(),
                        transpiled: zod.unknown(),
                    })
                )
                .optional()
                .describe('Values for each input defined in inputs_schema.'),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFunctionsInvocationsCreateResponseConfigurationOneFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .optional()
                .describe('Event filters that control which events trigger this function.'),
            masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMin)
                        .max(hogFunctionsInvocationsCreateResponseConfigurationOneMaskingOneTtlMax)
                        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
                    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
                    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash expression. Auto-generated.'),
                })
                .nullish()
                .describe('PII masking configuration with TTL, threshold, and hash expression.'),
            mappings: zod
                .array(
                    zod.object({
                        name: zod.string().optional(),
                        inputs_schema: zod
                            .array(
                                zod.object({
                                    type: zod
                                        .enum([
                                            'string',
                                            'number',
                                            'boolean',
                                            'dictionary',
                                            'choice',
                                            'json',
                                            'integration',
                                            'integration_field',
                                            'email',
                                            'native_email',
                                            'posthog_assignee',
                                            'posthog_ticket_tags',
                                        ])
                                        .describe(
                                            '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                        ),
                                    key: zod.string(),
                                    label: zod.string().optional(),
                                    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    required: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemRequiredDefault
                                        ),
                                    default: zod.unknown().optional(),
                                    secret: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemSecretDefault
                                        ),
                                    hidden: zod
                                        .boolean()
                                        .default(
                                            hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemInputsSchemaItemHiddenDefault
                                        ),
                                    description: zod.string().optional(),
                                    integration: zod.string().optional(),
                                    integration_key: zod.string().optional(),
                                    requires_field: zod.string().optional(),
                                    integration_field: zod.string().optional(),
                                    requiredScopes: zod.string().optional(),
                                    templating: zod
                                        .union([
                                            zod.literal(true),
                                            zod.literal(false),
                                            zod.literal('hog'),
                                            zod.literal('liquid'),
                                        ])
                                        .optional()
                                        .describe(
                                            '* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'
                                        ),
                                })
                            )
                            .optional(),
                        inputs: zod
                            .record(
                                zod.string(),
                                zod.object({
                                    value: zod.unknown().optional(),
                                    templating: zod
                                        .enum(['hog', 'liquid'])
                                        .optional()
                                        .describe('* `hog` - hog\n* `liquid` - liquid'),
                                    bytecode: zod.array(zod.unknown()),
                                    order: zod.number(),
                                    transpiled: zod.unknown(),
                                })
                            )
                            .optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(
                                        hogFunctionsInvocationsCreateResponseConfigurationOneMappingsItemFiltersSourceDefault
                                    ),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                bytecode: zod.unknown().nullish(),
                                transpiled: zod.unknown().optional(),
                                filter_test_accounts: zod.boolean().optional(),
                                bytecode_error: zod.string().optional(),
                            })
                            .optional(),
                    })
                )
                .nullish()
                .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
            icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
            template: zod.object({
                id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
                name: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneNameMax)
                    .describe('Display name of the template.'),
                description: zod.string().nullish().describe('What this template does.'),
                code: zod.string().describe('Source code of the template.'),
                code_language: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneCodeLanguageMax)
                    .optional()
                    .describe("Programming language: 'hog' or 'javascript'."),
                inputs_schema: zod
                    .unknown()
                    .describe('Schema defining configurable inputs for functions created from this template.'),
                type: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneTypeMax)
                    .describe('Function type this template creates.'),
                status: zod
                    .string()
                    .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateOneStatusMax)
                    .optional()
                    .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
                category: zod.unknown().optional().describe('Category tags for organizing templates.'),
                free: zod.boolean().optional().describe('Whether available on free plans.'),
                icon_url: zod.string().nullish().describe("URL for the template's icon."),
                filters: zod.unknown().nullish().describe('Default event filters.'),
                masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
                mapping_templates: zod
                    .array(
                        zod.object({
                            name: zod.string().describe('Name of this mapping template.'),
                            include_by_default: zod
                                .boolean()
                                .nullish()
                                .describe('Whether this mapping is enabled by default.'),
                            use_all_events_by_default: zod
                                .boolean()
                                .nullish()
                                .describe(
                                    'Whether this mapping should match all events by default, hiding the event filter UI.'
                                ),
                            filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                            inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                            inputs_schema: zod
                                .unknown()
                                .nullish()
                                .describe('Additional input schema fields specific to this mapping.'),
                        })
                    )
                    .nullish()
                    .describe('Pre-defined mapping configurations for destination templates.'),
            }),
            template_id: zod
                .string()
                .max(hogFunctionsInvocationsCreateResponseConfigurationOneTemplateIdMax)
                .nullish()
                .describe('ID of the template to create this function from.'),
            status: zod
                .object({
                    state: zod
                        .union([
                            zod.literal(0),
                            zod.literal(1),
                            zod.literal(2),
                            zod.literal(3),
                            zod.literal(11),
                            zod.literal(12),
                        ])
                        .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
                    tokens: zod.number(),
                })
                .nullable(),
            execution_order: zod
                .number()
                .min(hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMin)
                .max(hogFunctionsInvocationsCreateResponseConfigurationOneExecutionOrderMax)
                .nullish()
                .describe('Execution priority for transformations. Lower values run first.'),
            _create_in_folder: zod.string().optional(),
            batch_export_id: zod.uuid().nullable(),
        })
        .describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFunctionsInvocationsCreateResponseMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    status: zod.string().describe('Invocation result status.'),
    logs: zod.array(zod.unknown()).describe('Execution logs from the test invocation.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

/**
 * Update the execution order of multiple HogFunctions.
 */
export const HogFunctionsRearrangePartialUpdateBody = /* @__PURE__ */ zod.object({
    orders: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Map of hog function UUIDs to their new execution_order values.'),
})

export const hogFunctionsRearrangePartialUpdateResponseNameMax = 400

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFunctionsRearrangePartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemRequiredDefault = false
export const hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemSecretDefault = false
export const hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemHiddenDefault = false
export const hogFunctionsRearrangePartialUpdateResponseFiltersOneSourceDefault = `events`
export const hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMin = 60
export const hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMax = 86400

export const hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault = false
export const hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault = false
export const hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault = false
export const hogFunctionsRearrangePartialUpdateResponseMappingsItemFiltersSourceDefault = `events`
export const hogFunctionsRearrangePartialUpdateResponseTemplateOneNameMax = 400

export const hogFunctionsRearrangePartialUpdateResponseTemplateOneCodeLanguageMax = 20

export const hogFunctionsRearrangePartialUpdateResponseTemplateOneTypeMax = 50

export const hogFunctionsRearrangePartialUpdateResponseTemplateOneStatusMax = 20

export const hogFunctionsRearrangePartialUpdateResponseTemplateIdMax = 400

export const hogFunctionsRearrangePartialUpdateResponseExecutionOrderMin = 0
export const hogFunctionsRearrangePartialUpdateResponseExecutionOrderMax = 32767

export const HogFunctionsRearrangePartialUpdateResponseItem = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsRearrangePartialUpdateResponseNameMax)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFunctionsRearrangePartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    bytecode: zod.unknown().nullable(),
    transpiled: zod.string().nullable(),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod
                    .boolean()
                    .default(hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemRequiredDefault),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemSecretDefault),
                hidden: zod.boolean().default(hogFunctionsRearrangePartialUpdateResponseInputsSchemaItemHiddenDefault),
                description: zod.string().optional(),
                integration: zod.string().optional(),
                integration_key: zod.string().optional(),
                requires_field: zod.string().optional(),
                integration_field: zod.string().optional(),
                requiredScopes: zod.string().optional(),
                templating: zod
                    .union([zod.literal(true), zod.literal(false), zod.literal('hog'), zod.literal('liquid')])
                    .optional()
                    .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()),
                order: zod.number(),
                transpiled: zod.unknown(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsRearrangePartialUpdateResponseFiltersOneSourceDefault),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMin)
                .max(hogFunctionsRearrangePartialUpdateResponseMaskingOneTtlMax)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(
                                    hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemRequiredDefault
                                ),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(
                                    hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemSecretDefault
                                ),
                            hidden: zod
                                .boolean()
                                .default(
                                    hogFunctionsRearrangePartialUpdateResponseMappingsItemInputsSchemaItemHiddenDefault
                                ),
                            description: zod.string().optional(),
                            integration: zod.string().optional(),
                            integration_key: zod.string().optional(),
                            requires_field: zod.string().optional(),
                            integration_field: zod.string().optional(),
                            requiredScopes: zod.string().optional(),
                            templating: zod
                                .union([
                                    zod.literal(true),
                                    zod.literal(false),
                                    zod.literal('hog'),
                                    zod.literal('liquid'),
                                ])
                                .optional()
                                .describe('* `True` - True\n* `False` - False\n* `hog` - hog\n* `liquid` - liquid'),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()),
                            order: zod.number(),
                            transpiled: zod.unknown(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsRearrangePartialUpdateResponseMappingsItemFiltersSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: zod.object({
        id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
        name: zod
            .string()
            .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneNameMax)
            .describe('Display name of the template.'),
        description: zod.string().nullish().describe('What this template does.'),
        code: zod.string().describe('Source code of the template.'),
        code_language: zod
            .string()
            .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneCodeLanguageMax)
            .optional()
            .describe("Programming language: 'hog' or 'javascript'."),
        inputs_schema: zod
            .unknown()
            .describe('Schema defining configurable inputs for functions created from this template.'),
        type: zod
            .string()
            .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneTypeMax)
            .describe('Function type this template creates.'),
        status: zod
            .string()
            .max(hogFunctionsRearrangePartialUpdateResponseTemplateOneStatusMax)
            .optional()
            .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
        category: zod.unknown().optional().describe('Category tags for organizing templates.'),
        free: zod.boolean().optional().describe('Whether available on free plans.'),
        icon_url: zod.string().nullish().describe("URL for the template's icon."),
        filters: zod.unknown().nullish().describe('Default event filters.'),
        masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
        mapping_templates: zod
            .array(
                zod.object({
                    name: zod.string().describe('Name of this mapping template.'),
                    include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
                    use_all_events_by_default: zod
                        .boolean()
                        .nullish()
                        .describe(
                            'Whether this mapping should match all events by default, hiding the event filter UI.'
                        ),
                    filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                    inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                    inputs_schema: zod
                        .unknown()
                        .nullish()
                        .describe('Additional input schema fields specific to this mapping.'),
                })
            )
            .nullish()
            .describe('Pre-defined mapping configurations for destination templates.'),
    }),
    template_id: zod
        .string()
        .max(hogFunctionsRearrangePartialUpdateResponseTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    status: zod
        .object({
            state: zod
                .union([
                    zod.literal(0),
                    zod.literal(1),
                    zod.literal(2),
                    zod.literal(3),
                    zod.literal(11),
                    zod.literal(12),
                ])
                .describe('* `0` - 0\n* `1` - 1\n* `2` - 2\n* `3` - 3\n* `11` - 11\n* `12` - 12'),
            tokens: zod.number(),
        })
        .nullable(),
    execution_order: zod
        .number()
        .min(hogFunctionsRearrangePartialUpdateResponseExecutionOrderMin)
        .max(hogFunctionsRearrangePartialUpdateResponseExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
    batch_export_id: zod.uuid().nullable(),
})
export const HogFunctionsRearrangePartialUpdateResponse = /* @__PURE__ */ zod.array(
    HogFunctionsRearrangePartialUpdateResponseItem
)

export const publicHogFunctionTemplatesListResponseResultsItemNameMax = 400

export const publicHogFunctionTemplatesListResponseResultsItemCodeLanguageMax = 20

export const publicHogFunctionTemplatesListResponseResultsItemTypeMax = 50

export const publicHogFunctionTemplatesListResponseResultsItemStatusMax = 20

export const PublicHogFunctionTemplatesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
            name: zod
                .string()
                .max(publicHogFunctionTemplatesListResponseResultsItemNameMax)
                .describe('Display name of the template.'),
            description: zod.string().nullish().describe('What this template does.'),
            code: zod.string().describe('Source code of the template.'),
            code_language: zod
                .string()
                .max(publicHogFunctionTemplatesListResponseResultsItemCodeLanguageMax)
                .optional()
                .describe("Programming language: 'hog' or 'javascript'."),
            inputs_schema: zod
                .unknown()
                .describe('Schema defining configurable inputs for functions created from this template.'),
            type: zod
                .string()
                .max(publicHogFunctionTemplatesListResponseResultsItemTypeMax)
                .describe('Function type this template creates.'),
            status: zod
                .string()
                .max(publicHogFunctionTemplatesListResponseResultsItemStatusMax)
                .optional()
                .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
            category: zod.unknown().optional().describe('Category tags for organizing templates.'),
            free: zod.boolean().optional().describe('Whether available on free plans.'),
            icon_url: zod.string().nullish().describe("URL for the template's icon."),
            filters: zod.unknown().nullish().describe('Default event filters.'),
            masking: zod.unknown().nullish().describe('Default PII masking configuration.'),
            mapping_templates: zod
                .array(
                    zod.object({
                        name: zod.string().describe('Name of this mapping template.'),
                        include_by_default: zod
                            .boolean()
                            .nullish()
                            .describe('Whether this mapping is enabled by default.'),
                        use_all_events_by_default: zod
                            .boolean()
                            .nullish()
                            .describe(
                                'Whether this mapping should match all events by default, hiding the event filter UI.'
                            ),
                        filters: zod.unknown().nullish().describe('Event filters specific to this mapping.'),
                        inputs: zod.unknown().nullish().describe('Input values specific to this mapping.'),
                        inputs_schema: zod
                            .unknown()
                            .nullish()
                            .describe('Additional input schema fields specific to this mapping.'),
                    })
                )
                .nullish()
                .describe('Pre-defined mapping configurations for destination templates.'),
        })
    ),
})
