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

export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeValueDefault = null
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
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault),
                                seq_time_interval: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault),
                                seq_time_value: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault),
                                total_periods: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault),
                                min_periods: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault),
                                explicit_datetime: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault),
                                value: zod
                                    .unknown()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeValueDefault),
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

export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault = null
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
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault),
                                seq_time_interval: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault),
                                seq_time_value: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault),
                                total_periods: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault),
                                min_periods: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault),
                                explicit_datetime: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault),
                                value: zod
                                    .unknown()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault),
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

export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault = null
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
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault
                                    ),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault
                                    ),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                    ),
                                seq_time_interval: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                    ),
                                seq_time_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault
                                    ),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault
                                    ),
                                total_periods: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault
                                    ),
                                min_periods: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault
                                    ),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault
                                    ),
                                explicit_datetime: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                    ),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                    ),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault
                                    ),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                    ),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault
                                    ),
                                value: zod
                                    .unknown()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault),
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
