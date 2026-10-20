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

export const platformAlertsUpdateBodyOneNameMax = 255

export const platformAlertsUpdateBodyOneSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsUpdateBodyOneSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsUpdateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodyOneCooldownMinutesMin = 0
export const platformAlertsUpdateBodyOneCooldownMinutesMax = 2147483647

export const PlatformAlertsUpdateBody = /* @__PURE__ */ zod
    .object({
        source_kind: zod
            .enum(['logs'])
            .describe('Product whose data the alert evaluates. It cannot change, so it must match the stored value.'),
        name: zod.string().max(platformAlertsUpdateBodyOneNameMax).describe('Human-readable name of the alert.'),
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
                            .min(platformAlertsUpdateBodyOneSourceConfigOneConditionThresholdCountMin)
                            .max(platformAlertsUpdateBodyOneSourceConfigOneConditionThresholdCountMax)
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
    .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.')

export const platformAlertsPartialUpdateBodyOneNameMax = 255

export const platformAlertsPartialUpdateBodyOneSourceConfigOneConditionThresholdCountMin = 0
export const platformAlertsPartialUpdateBodyOneSourceConfigOneConditionThresholdCountMax = 2147483647

export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyOneGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyOneGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyOneEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyOneDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyOneCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyOneCooldownMinutesMax = 2147483647

export const PlatformAlertsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        source_kind: zod
            .enum(['logs'])
            .describe('Product whose data the alert evaluates. It cannot change, so it must match the stored value.'),
        name: zod
            .string()
            .max(platformAlertsPartialUpdateBodyOneNameMax)
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
                            .min(platformAlertsPartialUpdateBodyOneSourceConfigOneConditionThresholdCountMin)
                            .max(platformAlertsPartialUpdateBodyOneSourceConfigOneConditionThresholdCountMax)
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
    .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.')

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
            "Time until which this group's notifications are muted. Must be in the future. Null clears the group's snooze. The group keeps being checked, and its firing stays open."
        ),
})
