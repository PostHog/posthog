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

export const cohortsCreateBodyNameMax = 400

export const cohortsCreateBodyDescriptionMax = 1000

export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsCreateBodyCreateStaticPersonIdsDefault = []

export const CohortsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsCreateBodyNameMax).nullish(),
    description: zod.string().max(cohortsCreateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).default(cohortsCreateBodyCreateStaticPersonIdsDefault),
})

export const cohortsUpdateBodyNameMax = 400

export const cohortsUpdateBodyDescriptionMax = 1000

export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsUpdateBodyCreateStaticPersonIdsDefault = []

export const CohortsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).default(cohortsUpdateBodyCreateStaticPersonIdsDefault),
})

export const cohortsPartialUpdateBodyNameMax = 400

export const cohortsPartialUpdateBodyDescriptionMax = 1000

export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsPartialUpdateBodyCreateStaticPersonIdsDefault = []

export const CohortsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsPartialUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault
                                    ),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).default(cohortsPartialUpdateBodyCreateStaticPersonIdsDefault),
})

export const CohortsAddPersonsToStaticCohortPartialUpdateBody = /* @__PURE__ */ zod.object({
    person_ids: zod.array(zod.uuid()).optional().describe('List of person UUIDs to add to the cohort'),
})

export const CohortsRemovePersonFromStaticCohortPartialUpdateBody = /* @__PURE__ */ zod.object({
    person_id: zod.uuid().optional().describe('Person UUID to remove from the cohort'),
})
