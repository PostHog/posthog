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

export const platformAlertsCreateBodyOneNameDefault = `Untitled alert`
export const platformAlertsCreateBodyOneNameMax = 255

export const platformAlertsCreateBodyOneEnabledDefault = true
export const platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsCreateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyOneEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyOneDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyOneCooldownMinutesDefault = 0
export const platformAlertsCreateBodyOneCooldownMinutesMin = 0
export const platformAlertsCreateBodyOneCooldownMinutesMax = 2147483647

export const PlatformAlertsCreateBody = /* @__PURE__ */ zod
    .object({
        source_kind: zod
            .enum(['logs'])
            .describe('Product whose data the alert evaluates. It cannot change after the create.'),
        name: zod
            .string()
            .max(platformAlertsCreateBodyOneNameMax)
            .default(platformAlertsCreateBodyOneNameDefault)
            .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
        enabled: zod
            .boolean()
            .default(platformAlertsCreateBodyOneEnabledDefault)
            .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
        source_config: zod
            .object({
                filters: zod
                    .object({
                        filterGroup: zod
                            .union([
                                zod.object({
                                    type: zod.enum(['AND', 'OR']),
                                    values: zod.array(
                                        zod
                                            .record(zod.string(), zod.unknown())
                                            .describe(
                                                'Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'
                                            )
                                    ),
                                }),
                                zod.null(),
                            ])
                            .optional(),
                        serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
                        severityLevels: zod
                            .union([
                                zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])),
                                zod.null(),
                            ])
                            .optional(),
                    })
                    .describe(
                        'The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property filters. An enabled alert needs at least one.'
                    ),
                condition: zod
                    .object({
                        threshold_count: zod
                            .number()
                            .min(platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMin)
                            .max(platformAlertsCreateBodyOneSourceConfigOneConditionThresholdCountMax)
                            .describe(
                                'Number of matching log entries in the window that breaches the threshold. Use 0 with the above operator to fire on any matching log.'
                            ),
                        threshold_operator: zod
                            .enum(['above', 'below'])
                            .describe('Whether the alert fires when the count is above or below the threshold.'),
                        window_minutes: zod
                            .union([zod.literal(5), zod.literal(10), zod.literal(15), zod.literal(30), zod.literal(60)])
                            .describe('Time window in minutes over which logs are counted.'),
                    })
                    .describe('The bound the count is checked against.'),
            })
            .describe('Settings for a logs alert. The bound the alert is evaluated against is under condition.'),
        grouping: zod
            .object({
                mode: zod
                    .enum(['single', 'by_result_labels'])
                    .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                    .describe(
                        'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                    ),
                keys: zod
                    .array(zod.string())
                    .optional()
                    .describe(
                        'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                    ),
                max_instances: zod
                    .number()
                    .min(1)
                    .max(platformAlertsCreateBodyOneGroupingOneMaxInstancesMax)
                    .default(platformAlertsCreateBodyOneGroupingOneMaxInstancesDefault)
                    .describe(
                        'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                    ),
                on_overflow: zod
                    .enum(['degrade_visible'])
                    .describe('\* `degrade_visible` - Degrade visible')
                    .default(platformAlertsCreateBodyOneGroupingOneOnOverflowDefault)
                    .describe(
                        'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                    ),
            })
            .optional()
            .describe('How the alert splits its results into instances. Defaults to mode single.'),
        schedule_restriction: zod
            .union([
                zod.object({
                    blocked_windows: zod
                        .array(
                            zod.object({
                                start: zod
                                    .string()
                                    .describe(
                                        'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                    ),
                                end: zod
                                    .string()
                                    .describe(
                                        'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                    ),
                            })
                        )
                        .describe(
                            'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours. Defaults to null.'
            ),
        evaluation_periods: zod
            .number()
            .min(1)
            .max(platformAlertsCreateBodyOneEvaluationPeriodsMax)
            .default(platformAlertsCreateBodyOneEvaluationPeriodsDefault)
            .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
        datapoints_to_alarm: zod
            .number()
            .min(1)
            .max(platformAlertsCreateBodyOneDatapointsToAlarmMax)
            .default(platformAlertsCreateBodyOneDatapointsToAlarmDefault)
            .describe(
                'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
            ),
        cooldown_minutes: zod
            .number()
            .min(platformAlertsCreateBodyOneCooldownMinutesMin)
            .max(platformAlertsCreateBodyOneCooldownMinutesMax)
            .default(platformAlertsCreateBodyOneCooldownMinutesDefault)
            .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
    })
    .describe('The settings of a new alert. Every one but source_config has a default, which is stored.')

export const platformAlertsUpdateBodyOneNameMax = 255

export const platformAlertsUpdateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodyOneCooldownMinutesMin = 0
export const platformAlertsUpdateBodyOneCooldownMinutesMax = 2147483647

export const platformAlertsUpdateBodyTwoNameMax = 255

export const platformAlertsUpdateBodyTwoSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsUpdateBodyTwoSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsUpdateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodyTwoEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodyTwoDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodyTwoCooldownMinutesMin = 0
export const platformAlertsUpdateBodyTwoCooldownMinutesMax = 2147483647

export const PlatformAlertsUpdateBody = /* @__PURE__ */ zod.union([
    zod
        .object({
            source_kind: zod
                .enum(['insight'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod.string().max(platformAlertsUpdateBodyOneNameMax).describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    insight_id: zod
                        .number()
                        .describe('The insight the alert checks. It cannot change through this API.'),
                    condition: zod
                        .object({
                            threshold: zod
                                .union([
                                    zod.object({
                                        bounds: zod
                                            .union([
                                                zod.object({
                                                    lower: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Alert fires when the value drops below this number.'
                                                        ),
                                                    upper: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe('Alert fires when the value exceeds this number.'),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        type: zod
                                            .enum(['absolute', 'percentage'])
                                            .describe(
                                                'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .describe(
                                    "The bounds the insight's value is checked against, absolute or as a percentage change."
                                ),
                            comparison: zod
                                .object({
                                    type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
                                })
                                .describe(
                                    'How the value is compared: as it is, or as an increase or decrease from the previous interval.'
                                ),
                            detector: zod
                                .null()
                                .optional()
                                .describe(
                                    'Always null. The platform owns threshold alerts only, so no detector applies.'
                                ),
                        })
                        .describe("The bound the insight's value is checked against."),
                })
                .describe('Settings for a insight alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsUpdateBodyOneGroupingOneMaxInstancesMax)
                        .default(platformAlertsUpdateBodyOneGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsUpdateBodyOneGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyOneEvaluationPeriodsMax)
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyOneDatapointsToAlarmMax)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsUpdateBodyOneCooldownMinutesMin)
                .max(platformAlertsUpdateBodyOneCooldownMinutesMax)
                .describe('Minimum minutes between notifications for the same alert.'),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['logs'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod.string().max(platformAlertsUpdateBodyTwoNameMax).describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            filterGroup: zod
                                .union([
                                    zod.object({
                                        type: zod.enum(['AND', 'OR']),
                                        values: zod.array(
                                            zod
                                                .record(zod.string(), zod.unknown())
                                                .describe(
                                                    'Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'
                                                )
                                        ),
                                    }),
                                    zod.null(),
                                ])
                                .optional(),
                            serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
                            severityLevels: zod
                                .union([
                                    zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])),
                                    zod.null(),
                                ])
                                .optional(),
                        })
                        .describe(
                            'The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property filters. An enabled alert needs at least one.'
                        ),
                    condition: zod
                        .object({
                            threshold_count: zod
                                .number()
                                .min(platformAlertsUpdateBodyTwoSourceConfigOneConditionThresholdCountMin)
                                .max(platformAlertsUpdateBodyTwoSourceConfigOneConditionThresholdCountMax)
                                .describe(
                                    'Number of matching log entries in the window that breaches the threshold. Use 0 with the above operator to fire on any matching log.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires when the count is above or below the threshold.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes over which logs are counted.'),
                        })
                        .describe('The bound the count is checked against.'),
                })
                .describe('Settings for a logs alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsUpdateBodyTwoGroupingOneMaxInstancesMax)
                        .default(platformAlertsUpdateBodyTwoGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsUpdateBodyTwoGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyTwoEvaluationPeriodsMax)
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyTwoDatapointsToAlarmMax)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsUpdateBodyTwoCooldownMinutesMin)
                .max(platformAlertsUpdateBodyTwoCooldownMinutesMax)
                .describe('Minimum minutes between notifications for the same alert.'),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
])

export const platformAlertsPartialUpdateBodyOneNameMax = 255

export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyOneCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyOneCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyTwoNameMax = 255

export const platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyTwoEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyTwoDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyTwoCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyTwoCooldownMinutesMax = 2147483647

export const PlatformAlertsPartialUpdateBody = /* @__PURE__ */ zod.union([
    zod
        .object({
            source_kind: zod
                .enum(['insight'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyOneNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    insight_id: zod
                        .number()
                        .describe('The insight the alert checks. It cannot change through this API.'),
                    condition: zod
                        .object({
                            threshold: zod
                                .union([
                                    zod.object({
                                        bounds: zod
                                            .union([
                                                zod.object({
                                                    lower: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Alert fires when the value drops below this number.'
                                                        ),
                                                    upper: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe('Alert fires when the value exceeds this number.'),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional(),
                                        type: zod
                                            .enum(['absolute', 'percentage'])
                                            .describe(
                                                'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                                            ),
                                    }),
                                    zod.null(),
                                ])
                                .describe(
                                    "The bounds the insight's value is checked against, absolute or as a percentage change."
                                ),
                            comparison: zod
                                .object({
                                    type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
                                })
                                .describe(
                                    'How the value is compared: as it is, or as an increase or decrease from the previous interval.'
                                ),
                            detector: zod
                                .null()
                                .optional()
                                .describe(
                                    'Always null. The platform owns threshold alerts only, so no detector applies.'
                                ),
                        })
                        .describe("The bound the insight's value is checked against."),
                })
                .optional()
                .describe('Settings for a insight alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyOneGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyOneEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyOneDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyOneCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyOneCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['logs'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyTwoNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            filterGroup: zod
                                .union([
                                    zod.object({
                                        type: zod.enum(['AND', 'OR']),
                                        values: zod.array(
                                            zod
                                                .record(zod.string(), zod.unknown())
                                                .describe(
                                                    'Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)'
                                                )
                                        ),
                                    }),
                                    zod.null(),
                                ])
                                .optional(),
                            serviceNames: zod.union([zod.array(zod.string()), zod.null()]).optional(),
                            severityLevels: zod
                                .union([
                                    zod.array(zod.enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])),
                                    zod.null(),
                                ])
                                .optional(),
                        })
                        .describe(
                            'The logs the alert counts: severityLevels, serviceNames, or a filterGroup of property filters. An enabled alert needs at least one.'
                        ),
                    condition: zod
                        .object({
                            threshold_count: zod
                                .number()
                                .min(platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMin)
                                .max(platformAlertsPartialUpdateBodyTwoSourceConfigOneConditionThresholdCountMax)
                                .describe(
                                    'Number of matching log entries in the window that breaches the threshold. Use 0 with the above operator to fire on any matching log.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires when the count is above or below the threshold.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes over which logs are counted.'),
                        })
                        .describe('The bound the count is checked against.'),
                })
                .optional()
                .describe('Settings for a logs alert. The bound the alert is evaluated against is under condition.'),
            grouping: zod
                .object({
                    mode: zod
                        .enum(['single', 'by_result_labels'])
                        .describe('\* `single` - Single\n\* `by_result_labels` - By result labels')
                        .describe(
                            'single keeps one instance for the whole alert. by_result_labels keeps one instance per distinct value of the labels in keys, so each group fires and resolves on its own.\n\n\* `single` - Single\n\* `by_result_labels` - By result labels'
                        ),
                    keys: zod
                        .array(zod.string())
                        .optional()
                        .describe(
                            'Result labels whose values make a group, such as service_name. Empty for mode single, required for by_result_labels. Changing them deletes the existing instances and closes their notification threads without a message.'
                        ),
                    max_instances: zod
                        .number()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyTwoGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyTwoGroupingOneOnOverflowDefault)
                        .describe(
                            'What happens to groups past max_instances. degrade_visible names how many were left out.\n\n\* `degrade_visible` - Degrade visible'
                        ),
                })
                .optional()
                .describe('How the alert splits its results into instances.'),
            schedule_restriction: zod
                .union([
                    zod.object({
                        blocked_windows: zod
                            .array(
                                zod.object({
                                    start: zod
                                        .string()
                                        .describe(
                                            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                        ),
                                    end: zod
                                        .string()
                                        .describe(
                                            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                        ),
                                })
                            )
                            .describe(
                                'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not notify. Null means no quiet hours.'
                ),
            evaluation_periods: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyTwoEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyTwoDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyTwoCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyTwoCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
])

/**
 * @summary Snooze one group of a grouped alert
 */
export const platformAlertsSnoozeGroupCreateBodyGroupingKeyMax = 255

export const PlatformAlertsSnoozeGroupCreateBody = /* @__PURE__ */ zod.object({
    grouping_key: zod
        .string()
        .max(platformAlertsSnoozeGroupCreateBodyGroupingKeyMax)
        .describe("Key of the group to snooze, as the grouping_key of one of the alert's instances."),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe(
            "Time until which this group's notifications are muted. Must be in the future and at most 30 days away. Null clears the group's snooze. The group keeps being checked, and its firing stays open."
        ),
})
