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

/**
 * Add a receiver that routes can send alerts to.
 */
export const platformAlertReceiversCreateBodyNameMax = 255

export const PlatformAlertReceiversCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(platformAlertReceiversCreateBodyNameMax)
        .describe('Name of the receiver, unique in the project.'),
    enabled: zod.boolean().optional().describe('Whether routes send to this receiver. Defaults to true.'),
    type: zod
        .enum(['slack', 'webhook', 'teams', 'discord'])
        .describe('\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord')
        .describe(
            'Notification destination type.\n\n\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod
        .url()
        .optional()
        .describe(
            'HTTPS endpoint to post to. Required for webhook, teams and discord. Send it again on every update that changes the destination, because reads return it redacted.'
        ),
})

/**
 * Change a receiver. Destination fields replace the stored destination and need the type.
 */
export const platformAlertReceiversPartialUpdateBodyNameMax = 255

export const PlatformAlertReceiversPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(platformAlertReceiversPartialUpdateBodyNameMax)
        .optional()
        .describe('Name of the receiver, unique in the project.'),
    enabled: zod.boolean().optional().describe('Whether routes send to this receiver. Defaults to true.'),
    type: zod
        .enum(['slack', 'webhook', 'teams', 'discord'])
        .describe('\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord')
        .optional()
        .describe(
            'Notification destination type.\n\n\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod
        .url()
        .optional()
        .describe(
            'HTTPS endpoint to post to. Required for webhook, teams and discord. Send it again on every update that changes the destination, because reads return it redacted.'
        ),
})

/**
 * Add a route. Every alert whose labels match it also sends to its receiver.
 */

export const PlatformAlertRoutesCreateBody = /* @__PURE__ */ zod.object({
    receiver_id: zod.uuid().describe('ID of the receiver this route sends to.'),
    matchers: zod
        .array(
            zod.object({
                label: zod.string().describe('Name of an alert label, such as team.'),
                value: zod.string().describe('The value the label must equal, such as checkout.'),
            })
        )
        .optional()
        .describe(
            'Label conditions, all of which must hold for an alert to match. An empty list matches every alert in the project.'
        ),
    event_kinds: zod
        .array(
            zod
                .enum(['firing', 'resolved', 'errored', 'broken'])
                .describe(
                    '\* `firing` - firing\n\* `resolved` - resolved\n\* `errored` - errored\n\* `broken` - broken'
                )
        )
        .min(1)
        .optional()
        .describe('The alert transitions the receiver hears about through this route. Defaults to every kind.'),
    enabled: zod.boolean().optional().describe('Whether this route sends. Defaults to true.'),
})

/**
 * Change a route. Fields left out keep their stored value.
 */

export const PlatformAlertRoutesPartialUpdateBody = /* @__PURE__ */ zod.object({
    receiver_id: zod.uuid().optional().describe('ID of the receiver this route sends to.'),
    matchers: zod
        .array(
            zod.object({
                label: zod.string().describe('Name of an alert label, such as team.'),
                value: zod.string().describe('The value the label must equal, such as checkout.'),
            })
        )
        .optional()
        .describe(
            'Label conditions, all of which must hold for an alert to match. An empty list matches every alert in the project.'
        ),
    event_kinds: zod
        .array(
            zod
                .enum(['firing', 'resolved', 'errored', 'broken'])
                .describe(
                    '\* `firing` - firing\n\* `resolved` - resolved\n\* `errored` - errored\n\* `broken` - broken'
                )
        )
        .min(1)
        .optional()
        .describe('The alert transitions the receiver hears about through this route. Defaults to every kind.'),
    enabled: zod.boolean().optional().describe('Whether this route sends. Defaults to true.'),
})

/**
 * Create an alert on the platform. The request body depends on source_kind, which picks the source product and the shape of source_config. The alert notifies nobody until a destination is added.
 * @summary Create an alert
 */
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

export const platformAlertsCreateBodyTwoNameDefault = `Untitled alert`
export const platformAlertsCreateBodyTwoNameMax = 255

export const platformAlertsCreateBodyTwoEnabledDefault = true
export const platformAlertsCreateBodyTwoSourceConfigOneQueryMax = 10000

export const platformAlertsCreateBodyTwoSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsCreateBodyTwoGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyTwoGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyTwoGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyTwoEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyTwoEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyTwoDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyTwoDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyTwoCooldownMinutesDefault = 0
export const platformAlertsCreateBodyTwoCooldownMinutesMin = 0
export const platformAlertsCreateBodyTwoCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyThreeNameDefault = `Untitled alert`
export const platformAlertsCreateBodyThreeNameMax = 255

export const platformAlertsCreateBodyThreeEnabledDefault = true
export const platformAlertsCreateBodyThreeSourceConfigOneConditionThresholdMin = 0

export const platformAlertsCreateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyThreeEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyThreeEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyThreeDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyThreeDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyThreeCooldownMinutesDefault = 0
export const platformAlertsCreateBodyThreeCooldownMinutesMin = 0
export const platformAlertsCreateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyFourNameDefault = `Untitled alert`
export const platformAlertsCreateBodyFourNameMax = 255

export const platformAlertsCreateBodyFourEnabledDefault = true
export const platformAlertsCreateBodyFourSourceConfigOneDestinationIdsMax = 100

export const platformAlertsCreateBodyFourSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsCreateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyFourEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyFourEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyFourDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyFourDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyFourCooldownMinutesDefault = 0
export const platformAlertsCreateBodyFourCooldownMinutesMin = 0
export const platformAlertsCreateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsCreateBodyFiveNameDefault = `Untitled alert`
export const platformAlertsCreateBodyFiveNameMax = 255

export const platformAlertsCreateBodyFiveEnabledDefault = true
export const platformAlertsCreateBodyFiveSourceConfigOneSourceIdsMax = 100

export const platformAlertsCreateBodyFiveSourceConfigOneGroupByDefault = `source`
export const platformAlertsCreateBodyFiveSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsCreateBodyFiveSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsCreateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsCreateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsCreateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsCreateBodyFiveEvaluationPeriodsDefault = 1
export const platformAlertsCreateBodyFiveEvaluationPeriodsMax = 10

export const platformAlertsCreateBodyFiveDatapointsToAlarmDefault = 1
export const platformAlertsCreateBodyFiveDatapointsToAlarmMax = 10

export const platformAlertsCreateBodyFiveCooldownMinutesDefault = 0
export const platformAlertsCreateBodyFiveCooldownMinutesMin = 0
export const platformAlertsCreateBodyFiveCooldownMinutesMax = 2147483647

export const PlatformAlertsCreateBody = /* @__PURE__ */ zod.union([
    zod
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
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['metrics'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyTwoNameMax)
                .default(platformAlertsCreateBodyTwoNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyTwoEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsCreateBodyTwoSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsCreateBodyTwoSourceConfigOneConditionKindDefault)
                                .describe(
                                    "threshold compares each series' latest value with `threshold`. present fires for every series the query returns, for a query that already filters to the series in breach."
                                ),
                            operator: zod
                                .union([zod.enum(['gt', 'gte', 'lt', 'lte', 'eq', 'ne']), zod.null()])
                                .optional()
                                .describe("How a series' value compares with `threshold`. Required for a threshold."),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('The value a series is compared with. Required for a threshold.'),
                        })
                        .describe('When a series is in breach.'),
                })
                .describe('Settings for a metrics alert. The bound the alert is evaluated against is under condition.'),
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
                        .max(platformAlertsCreateBodyTwoGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyTwoGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyTwoGroupingOneOnOverflowDefault)
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
                .max(platformAlertsCreateBodyTwoEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyTwoEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyTwoDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyTwoDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyTwoCooldownMinutesMin)
                .max(platformAlertsCreateBodyTwoCooldownMinutesMax)
                .default(platformAlertsCreateBodyTwoCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['traces'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyThreeNameMax)
                .default(platformAlertsCreateBodyThreeNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyThreeEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            serviceNames: zod
                                .array(zod.string())
                                .optional()
                                .describe('Services whose requests the alert measures.'),
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
                                .optional()
                                .describe(
                                    'Span, span attribute and resource attribute filters, as the tracing scene sends.'
                                ),
                        })
                        .optional()
                        .describe('The requests the alert measures.'),
                    condition: zod
                        .object({
                            measure: zod
                                .enum(['request_count', 'error_count', 'error_rate', 'latency'])
                                .describe(
                                    'What the alert measures over requests: their count, the count with an error status, the share with an error status, or a latency percentile. A request is a trace root, server or consumer span.'
                                ),
                            percentile: zod
                                .union([
                                    zod.union([zod.literal(50), zod.literal(90), zod.literal(95), zod.literal(99)]),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('The latency percentile. Required for latency.'),
                            threshold: zod
                                .number()
                                .min(platformAlertsCreateBodyThreeSourceConfigOneConditionThresholdMin)
                                .describe(
                                    'The bound: a count for request_count and error_count, a fraction from 0 to 1 for error_rate, milliseconds for latency.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires above or below it.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes that each check measures.'),
                        })
                        .describe('The bound the measure is checked against.'),
                })
                .describe('Settings for a traces alert. The bound the alert is evaluated against is under condition.'),
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
                        .max(platformAlertsCreateBodyThreeGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyThreeGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyThreeGroupingOneOnOverflowDefault)
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
                .max(platformAlertsCreateBodyThreeEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyThreeEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyThreeDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyThreeDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyThreeCooldownMinutesMin)
                .max(platformAlertsCreateBodyThreeCooldownMinutesMax)
                .default(platformAlertsCreateBodyThreeCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_destination'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyFourNameMax)
                .default(platformAlertsCreateBodyFourNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyFourEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    destination_ids: zod
                        .array(zod.uuid())
                        .max(platformAlertsCreateBodyFourSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFourSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .describe(
                    'Settings for a warehouse_destination alert. The bound the alert is evaluated against is under condition.'
                ),
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
                        .max(platformAlertsCreateBodyFourGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyFourGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyFourGroupingOneOnOverflowDefault)
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
                .max(platformAlertsCreateBodyFourEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyFourEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyFourDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyFourDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyFourCooldownMinutesMin)
                .max(platformAlertsCreateBodyFourCooldownMinutesMax)
                .default(platformAlertsCreateBodyFourCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe('Product whose data the alert evaluates. It cannot change after the create.'),
            name: zod
                .string()
                .max(platformAlertsCreateBodyFiveNameMax)
                .default(platformAlertsCreateBodyFiveNameDefault)
                .describe("Human-readable name of the alert. Defaults to 'Untitled alert'."),
            enabled: zod
                .boolean()
                .default(platformAlertsCreateBodyFiveEnabledDefault)
                .describe('Whether the alert is evaluated on schedule. Defaults to true.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.uuid())
                        .max(platformAlertsCreateBodyFiveSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsCreateBodyFiveSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFiveSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsCreateBodyFiveSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .describe(
                    'Settings for a warehouse_source alert. The bound the alert is evaluated against is under condition.'
                ),
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
                        .max(platformAlertsCreateBodyFiveGroupingOneMaxInstancesMax)
                        .default(platformAlertsCreateBodyFiveGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsCreateBodyFiveGroupingOneOnOverflowDefault)
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
                .max(platformAlertsCreateBodyFiveEvaluationPeriodsMax)
                .default(platformAlertsCreateBodyFiveEvaluationPeriodsDefault)
                .describe('Number of recent checks considered when deciding to fire. Defaults to 1.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsCreateBodyFiveDatapointsToAlarmMax)
                .default(platformAlertsCreateBodyFiveDatapointsToAlarmDefault)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods. Defaults to 1.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsCreateBodyFiveCooldownMinutesMin)
                .max(platformAlertsCreateBodyFiveCooldownMinutesMax)
                .default(platformAlertsCreateBodyFiveCooldownMinutesDefault)
                .describe('Minimum minutes between notifications for the same alert. Defaults to 0.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings of a new alert. Every one but source_config has a default, which is stored.'),
])

/**
 * Replace every setting of an alert the platform owns. source_kind must match the stored value.
 * @summary Replace an alert's settings
 */
export const platformAlertsUpdateBodyOneNameMax = 255

export const platformAlertsUpdateBodyOneSourceConfigOneSkipWeekendDefault = false
export const platformAlertsUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsDefault = 0
export const platformAlertsUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsMin = 0

export const platformAlertsUpdateBodyOneSourceConfigOneInvestigationAgentEnabledDefault = false
export const platformAlertsUpdateBodyOneSourceConfigOneInvestigationGatesNotificationsDefault = false
export const platformAlertsUpdateBodyOneSourceConfigOneInvestigationInconclusiveActionDefault = `notify`
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

export const platformAlertsUpdateBodyThreeNameMax = 255

export const platformAlertsUpdateBodyThreeSourceConfigOneQueryMax = 10000

export const platformAlertsUpdateBodyThreeSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsUpdateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodyThreeEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodyThreeDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodyThreeCooldownMinutesMin = 0
export const platformAlertsUpdateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsUpdateBodyFourNameMax = 255

export const platformAlertsUpdateBodyFourSourceConfigOneConditionThresholdMin = 0

export const platformAlertsUpdateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodyFourEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodyFourDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodyFourCooldownMinutesMin = 0
export const platformAlertsUpdateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsUpdateBodyFiveNameMax = 255

export const platformAlertsUpdateBodyFiveSourceConfigOneDestinationIdsMax = 100

export const platformAlertsUpdateBodyFiveSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsUpdateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodyFiveEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodyFiveDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodyFiveCooldownMinutesMin = 0
export const platformAlertsUpdateBodyFiveCooldownMinutesMax = 2147483647

export const platformAlertsUpdateBodySixNameMax = 255

export const platformAlertsUpdateBodySixSourceConfigOneSourceIdsMax = 100

export const platformAlertsUpdateBodySixSourceConfigOneGroupByDefault = `source`
export const platformAlertsUpdateBodySixSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsUpdateBodySixSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsUpdateBodySixGroupingOneMaxInstancesDefault = 100
export const platformAlertsUpdateBodySixGroupingOneMaxInstancesMax = 100

export const platformAlertsUpdateBodySixGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsUpdateBodySixEvaluationPeriodsMax = 10

export const platformAlertsUpdateBodySixDatapointsToAlarmMax = 10

export const platformAlertsUpdateBodySixCooldownMinutesMin = 0
export const platformAlertsUpdateBodySixCooldownMinutesMax = 2147483647

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
                                .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                                .optional()
                                .describe(
                                    "The anomaly detector the alert uses in place of its threshold, or null for a threshold alert. It can't change through this API."
                                ),
                        })
                        .describe("The bound the insight's value is checked against."),
                    config: zod
                        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                        .optional()
                        .describe(
                            "Which part of the insight the alert reads, such as the series and whether the current interval counts. It can't change through this API."
                        ),
                    skip_weekend: zod
                        .boolean()
                        .default(platformAlertsUpdateBodyOneSourceConfigOneSkipWeekendDefault)
                        .describe("Whether checks skip Saturdays and Sundays. It can't change through this API."),
                    evaluation_delay_intervals: zod
                        .number()
                        .min(platformAlertsUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsMin)
                        .default(platformAlertsUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsDefault)
                        .describe(
                            "How many of the most recent intervals a check leaves out, so late data can arrive. It can't change through this API."
                        ),
                    investigation_agent_enabled: zod
                        .boolean()
                        .default(platformAlertsUpdateBodyOneSourceConfigOneInvestigationAgentEnabledDefault)
                        .describe(
                            "Whether an AI agent investigates each firing of an anomaly alert. It can't change through this API."
                        ),
                    investigation_gates_notifications: zod
                        .boolean()
                        .default(platformAlertsUpdateBodyOneSourceConfigOneInvestigationGatesNotificationsDefault)
                        .describe(
                            "Whether a firing waits for the agent's verdict, and is dropped when the agent calls it a false positive. It can't change through this API."
                        ),
                    investigation_inconclusive_action: zod
                        .enum(['notify', 'suppress'])
                        .default(platformAlertsUpdateBodyOneSourceConfigOneInvestigationInconclusiveActionDefault)
                        .describe(
                            "What a waiting firing does when the agent's verdict is inconclusive. It can't change through this API."
                        ),
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
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
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
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['metrics'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod.string().max(platformAlertsUpdateBodyThreeNameMax).describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsUpdateBodyThreeSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsUpdateBodyThreeSourceConfigOneConditionKindDefault)
                                .describe(
                                    "threshold compares each series' latest value with `threshold`. present fires for every series the query returns, for a query that already filters to the series in breach."
                                ),
                            operator: zod
                                .union([zod.enum(['gt', 'gte', 'lt', 'lte', 'eq', 'ne']), zod.null()])
                                .optional()
                                .describe("How a series' value compares with `threshold`. Required for a threshold."),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('The value a series is compared with. Required for a threshold.'),
                        })
                        .describe('When a series is in breach.'),
                })
                .describe('Settings for a metrics alert. The bound the alert is evaluated against is under condition.'),
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
                        .max(platformAlertsUpdateBodyThreeGroupingOneMaxInstancesMax)
                        .default(platformAlertsUpdateBodyThreeGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsUpdateBodyThreeGroupingOneOnOverflowDefault)
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
                .max(platformAlertsUpdateBodyThreeEvaluationPeriodsMax)
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyThreeDatapointsToAlarmMax)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsUpdateBodyThreeCooldownMinutesMin)
                .max(platformAlertsUpdateBodyThreeCooldownMinutesMax)
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['traces'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod.string().max(platformAlertsUpdateBodyFourNameMax).describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            serviceNames: zod
                                .array(zod.string())
                                .optional()
                                .describe('Services whose requests the alert measures.'),
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
                                .optional()
                                .describe(
                                    'Span, span attribute and resource attribute filters, as the tracing scene sends.'
                                ),
                        })
                        .optional()
                        .describe('The requests the alert measures.'),
                    condition: zod
                        .object({
                            measure: zod
                                .enum(['request_count', 'error_count', 'error_rate', 'latency'])
                                .describe(
                                    'What the alert measures over requests: their count, the count with an error status, the share with an error status, or a latency percentile. A request is a trace root, server or consumer span.'
                                ),
                            percentile: zod
                                .union([
                                    zod.union([zod.literal(50), zod.literal(90), zod.literal(95), zod.literal(99)]),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('The latency percentile. Required for latency.'),
                            threshold: zod
                                .number()
                                .min(platformAlertsUpdateBodyFourSourceConfigOneConditionThresholdMin)
                                .describe(
                                    'The bound: a count for request_count and error_count, a fraction from 0 to 1 for error_rate, milliseconds for latency.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires above or below it.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes that each check measures.'),
                        })
                        .describe('The bound the measure is checked against.'),
                })
                .describe('Settings for a traces alert. The bound the alert is evaluated against is under condition.'),
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
                        .max(platformAlertsUpdateBodyFourGroupingOneMaxInstancesMax)
                        .default(platformAlertsUpdateBodyFourGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsUpdateBodyFourGroupingOneOnOverflowDefault)
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
                .max(platformAlertsUpdateBodyFourEvaluationPeriodsMax)
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyFourDatapointsToAlarmMax)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsUpdateBodyFourCooldownMinutesMin)
                .max(platformAlertsUpdateBodyFourCooldownMinutesMax)
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_destination'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod.string().max(platformAlertsUpdateBodyFiveNameMax).describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    destination_ids: zod
                        .array(zod.uuid())
                        .max(platformAlertsUpdateBodyFiveSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsUpdateBodyFiveSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .describe(
                    'Settings for a warehouse_destination alert. The bound the alert is evaluated against is under condition.'
                ),
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
                        .max(platformAlertsUpdateBodyFiveGroupingOneMaxInstancesMax)
                        .default(platformAlertsUpdateBodyFiveGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsUpdateBodyFiveGroupingOneOnOverflowDefault)
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
                .max(platformAlertsUpdateBodyFiveEvaluationPeriodsMax)
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodyFiveDatapointsToAlarmMax)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsUpdateBodyFiveCooldownMinutesMin)
                .max(platformAlertsUpdateBodyFiveCooldownMinutesMax)
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod.string().max(platformAlertsUpdateBodySixNameMax).describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.uuid())
                        .max(platformAlertsUpdateBodySixSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsUpdateBodySixSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsUpdateBodySixSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsUpdateBodySixSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .describe(
                    'Settings for a warehouse_source alert. The bound the alert is evaluated against is under condition.'
                ),
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
                        .max(platformAlertsUpdateBodySixGroupingOneMaxInstancesMax)
                        .default(platformAlertsUpdateBodySixGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsUpdateBodySixGroupingOneOnOverflowDefault)
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
                .max(platformAlertsUpdateBodySixEvaluationPeriodsMax)
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsUpdateBodySixDatapointsToAlarmMax)
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsUpdateBodySixCooldownMinutesMin)
                .max(platformAlertsUpdateBodySixCooldownMinutesMax)
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
])

/**
 * Change some settings of an alert the platform owns. Settings left out keep their stored value. A source_kind that is sent must match the stored value.
 * @summary Change an alert
 */
export const platformAlertsPartialUpdateBodyOneNameMax = 255

export const platformAlertsPartialUpdateBodyOneSourceConfigOneSkipWeekendDefault = false
export const platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsDefault = 0
export const platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsMin = 0

export const platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationAgentEnabledDefault = false
export const platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationGatesNotificationsDefault = false
export const platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationInconclusiveActionDefault = `notify`
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

export const platformAlertsPartialUpdateBodyThreeNameMax = 255

export const platformAlertsPartialUpdateBodyThreeSourceConfigOneQueryMax = 10000

export const platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionKindDefault = `threshold`
export const platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyThreeGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyThreeEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyThreeDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyThreeCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyThreeCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyFourNameMax = 255

export const platformAlertsPartialUpdateBodyFourSourceConfigOneConditionThresholdMin = 0

export const platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyFourGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyFourEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyFourDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyFourCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyFourCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodyFiveNameMax = 255

export const platformAlertsPartialUpdateBodyFiveSourceConfigOneDestinationIdsMax = 100

export const platformAlertsPartialUpdateBodyFiveSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodyFiveGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodyFiveEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodyFiveDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodyFiveCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodyFiveCooldownMinutesMax = 2147483647

export const platformAlertsPartialUpdateBodySixNameMax = 255

export const platformAlertsPartialUpdateBodySixSourceConfigOneSourceIdsMax = 100

export const platformAlertsPartialUpdateBodySixSourceConfigOneGroupByDefault = `source`
export const platformAlertsPartialUpdateBodySixSourceConfigOneIncludeBillingLimitsDefault = false
export const platformAlertsPartialUpdateBodySixSourceConfigOneEmailProjectMembersDefault = false
export const platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesDefault = 100
export const platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesMax = 100

export const platformAlertsPartialUpdateBodySixGroupingOneOnOverflowDefault = `degrade_visible`
export const platformAlertsPartialUpdateBodySixEvaluationPeriodsMax = 10

export const platformAlertsPartialUpdateBodySixDatapointsToAlarmMax = 10

export const platformAlertsPartialUpdateBodySixCooldownMinutesMin = 0
export const platformAlertsPartialUpdateBodySixCooldownMinutesMax = 2147483647

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
                                .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                                .optional()
                                .describe(
                                    "The anomaly detector the alert uses in place of its threshold, or null for a threshold alert. It can't change through this API."
                                ),
                        })
                        .describe("The bound the insight's value is checked against."),
                    config: zod
                        .union([zod.record(zod.string(), zod.unknown()), zod.null()])
                        .optional()
                        .describe(
                            "Which part of the insight the alert reads, such as the series and whether the current interval counts. It can't change through this API."
                        ),
                    skip_weekend: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyOneSourceConfigOneSkipWeekendDefault)
                        .describe("Whether checks skip Saturdays and Sundays. It can't change through this API."),
                    evaluation_delay_intervals: zod
                        .number()
                        .min(platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsMin)
                        .default(platformAlertsPartialUpdateBodyOneSourceConfigOneEvaluationDelayIntervalsDefault)
                        .describe(
                            "How many of the most recent intervals a check leaves out, so late data can arrive. It can't change through this API."
                        ),
                    investigation_agent_enabled: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationAgentEnabledDefault)
                        .describe(
                            "Whether an AI agent investigates each firing of an anomaly alert. It can't change through this API."
                        ),
                    investigation_gates_notifications: zod
                        .boolean()
                        .default(
                            platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationGatesNotificationsDefault
                        )
                        .describe(
                            "Whether a firing waits for the agent's verdict, and is dropped when the agent calls it a false positive. It can't change through this API."
                        ),
                    investigation_inconclusive_action: zod
                        .enum(['notify', 'suppress'])
                        .default(
                            platformAlertsPartialUpdateBodyOneSourceConfigOneInvestigationInconclusiveActionDefault
                        )
                        .describe(
                            "What a waiting firing does when the agent's verdict is inconclusive. It can't change through this API."
                        ),
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
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
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
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['metrics'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyThreeNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    query: zod
                        .string()
                        .min(1)
                        .max(platformAlertsPartialUpdateBodyThreeSourceConfigOneQueryMax)
                        .describe(
                            "A PromQL expression over this project's metrics. Each series it returns is one group. For a threshold condition, leave the comparison out of the expression."
                        ),
                    condition: zod
                        .object({
                            kind: zod
                                .enum(['threshold', 'present'])
                                .default(platformAlertsPartialUpdateBodyThreeSourceConfigOneConditionKindDefault)
                                .describe(
                                    "threshold compares each series' latest value with `threshold`. present fires for every series the query returns, for a query that already filters to the series in breach."
                                ),
                            operator: zod
                                .union([zod.enum(['gt', 'gte', 'lt', 'lte', 'eq', 'ne']), zod.null()])
                                .optional()
                                .describe("How a series' value compares with `threshold`. Required for a threshold."),
                            threshold: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('The value a series is compared with. Required for a threshold.'),
                        })
                        .describe('When a series is in breach.'),
                })
                .optional()
                .describe('Settings for a metrics alert. The bound the alert is evaluated against is under condition.'),
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
                        .max(platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyThreeGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyThreeGroupingOneOnOverflowDefault)
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
                .max(platformAlertsPartialUpdateBodyThreeEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyThreeDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyThreeCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyThreeCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['traces'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyFourNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    filters: zod
                        .object({
                            serviceNames: zod
                                .array(zod.string())
                                .optional()
                                .describe('Services whose requests the alert measures.'),
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
                                .optional()
                                .describe(
                                    'Span, span attribute and resource attribute filters, as the tracing scene sends.'
                                ),
                        })
                        .optional()
                        .describe('The requests the alert measures.'),
                    condition: zod
                        .object({
                            measure: zod
                                .enum(['request_count', 'error_count', 'error_rate', 'latency'])
                                .describe(
                                    'What the alert measures over requests: their count, the count with an error status, the share with an error status, or a latency percentile. A request is a trace root, server or consumer span.'
                                ),
                            percentile: zod
                                .union([
                                    zod.union([zod.literal(50), zod.literal(90), zod.literal(95), zod.literal(99)]),
                                    zod.null(),
                                ])
                                .optional()
                                .describe('The latency percentile. Required for latency.'),
                            threshold: zod
                                .number()
                                .min(platformAlertsPartialUpdateBodyFourSourceConfigOneConditionThresholdMin)
                                .describe(
                                    'The bound: a count for request_count and error_count, a fraction from 0 to 1 for error_rate, milliseconds for latency.'
                                ),
                            threshold_operator: zod
                                .enum(['above', 'below'])
                                .describe('Whether the alert fires above or below it.'),
                            window_minutes: zod
                                .union([
                                    zod.literal(5),
                                    zod.literal(10),
                                    zod.literal(15),
                                    zod.literal(30),
                                    zod.literal(60),
                                ])
                                .describe('Time window in minutes that each check measures.'),
                        })
                        .describe('The bound the measure is checked against.'),
                })
                .optional()
                .describe('Settings for a traces alert. The bound the alert is evaluated against is under condition.'),
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
                        .max(platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyFourGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyFourGroupingOneOnOverflowDefault)
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
                .max(platformAlertsPartialUpdateBodyFourEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyFourDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyFourCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyFourCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_destination'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodyFiveNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    destination_ids: zod
                        .array(zod.uuid())
                        .max(platformAlertsPartialUpdateBodyFiveSourceConfigOneDestinationIdsMax)
                        .optional()
                        .describe(
                            'Warehouse destinations the alert watches. Empty watches every destination in the project, including destinations added later. The grouping must be by_result_labels with keys [destination_id].'
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodyFiveSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .optional()
                .describe(
                    'Settings for a warehouse_destination alert. The bound the alert is evaluated against is under condition.'
                ),
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
                        .max(platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodyFiveGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodyFiveGroupingOneOnOverflowDefault)
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
                .max(platformAlertsPartialUpdateBodyFiveEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodyFiveDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodyFiveCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodyFiveCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
    zod
        .object({
            source_kind: zod
                .enum(['warehouse_source'])
                .describe(
                    'Product whose data the alert evaluates. It cannot change, so it must match the stored value.'
                ),
            name: zod
                .string()
                .max(platformAlertsPartialUpdateBodySixNameMax)
                .optional()
                .describe('Human-readable name of the alert.'),
            enabled: zod.boolean().optional().describe('Whether the alert is evaluated on schedule.'),
            source_config: zod
                .object({
                    source_ids: zod
                        .array(zod.uuid())
                        .max(platformAlertsPartialUpdateBodySixSourceConfigOneSourceIdsMax)
                        .optional()
                        .describe(
                            'Warehouse sources the alert watches. Empty watches every source in the project, including sources added later.'
                        ),
                    group_by: zod
                        .enum(['schema', 'source'])
                        .default(platformAlertsPartialUpdateBodySixSourceConfigOneGroupByDefault)
                        .describe(
                            'schema keeps one alert instance, and sends one message, per failing table. source keeps one per source, whatever number of its tables fail. The grouping must be by_result_labels with keys [schema_id] or [source_id] to match.'
                        ),
                    include_billing_limits: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodySixSourceConfigOneIncludeBillingLimitsDefault)
                        .describe(
                            "Whether a table that stops syncing at the project's billing limit also fires the alert."
                        ),
                    email_project_members: zod
                        .boolean()
                        .default(platformAlertsPartialUpdateBodySixSourceConfigOneEmailProjectMembersDefault)
                        .describe(
                            'Whether project members who get data pipeline error emails also get an email when this alert fires or resolves.'
                        ),
                })
                .optional()
                .describe(
                    'Settings for a warehouse_source alert. The bound the alert is evaluated against is under condition.'
                ),
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
                        .max(platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesMax)
                        .default(platformAlertsPartialUpdateBodySixGroupingOneMaxInstancesDefault)
                        .describe(
                            'Most instances the alert keeps at once. Groups past it are not tracked, and the last message says how many were left out.'
                        ),
                    on_overflow: zod
                        .enum(['degrade_visible'])
                        .describe('\* `degrade_visible` - Degrade visible')
                        .default(platformAlertsPartialUpdateBodySixGroupingOneOnOverflowDefault)
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
                .max(platformAlertsPartialUpdateBodySixEvaluationPeriodsMax)
                .optional()
                .describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .min(1)
                .max(platformAlertsPartialUpdateBodySixDatapointsToAlarmMax)
                .optional()
                .describe(
                    'Number of breaching checks within evaluation_periods required to fire. Cannot exceed evaluation_periods.'
                ),
            cooldown_minutes: zod
                .number()
                .min(platformAlertsPartialUpdateBodySixCooldownMinutesMin)
                .max(platformAlertsPartialUpdateBodySixCooldownMinutesMax)
                .optional()
                .describe('Minimum minutes between notifications for the same alert.'),
            labels: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Labels that say who owns the alert and how urgent it is, such as {\"team\": \"checkout\", \"severity\": \"critical\"}. Names use letters, digits and underscores. alertname and names that start with posthog_ are reserved. Values cannot use templates.'
                ),
            annotations: zod
                .record(zod.string(), zod.string())
                .optional()
                .describe(
                    'Context for whoever responds, such as {\"runbook_url\": \"https:\/\/...\"}. Values can use {{ $labels.<name> }} for a grouping key or label of the alert, and {{ $value }}. An annotation whose name ends in _url must start with https:\/\/.'
                ),
        })
        .describe('The settings an edit can change. Each source kind subclasses it with a typed `source_config`.'),
])

/**
 * Add a notification destination to an alert. It hears the transitions in `event_kinds`. A PagerDuty destination opens an incident when the alert fires and resolves it when the alert resolves.
 */
export const platformAlertsDestinationsCreateBodyPagerdutySeverityDefault = `critical`
export const platformAlertsDestinationsCreateBodyPagerdutyRegionDefault = `us`

export const PlatformAlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams', 'discord', 'pagerduty'])
        .describe(
            '\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord\n\* `pagerduty` - PagerDuty'
        )
        .describe(
            'Notification destination type.\n\n\* `slack` - Slack\n\* `webhook` - Webhook\n\* `teams` - Microsoft Teams\n\* `discord` - Discord\n\* `pagerduty` - PagerDuty'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to post to. Required for webhook, teams and discord.'),
    pagerduty_routing_key: zod
        .string()
        .optional()
        .describe('Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.'),
    pagerduty_severity: zod
        .enum(['critical', 'error', 'warning', 'info'])
        .describe('\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info')
        .default(platformAlertsDestinationsCreateBodyPagerdutySeverityDefault)
        .describe(
            'Severity PagerDuty records on the incident. Used when type=pagerduty.\n\n\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info'
        ),
    pagerduty_region: zod
        .enum(['us', 'eu'])
        .describe('\* `us` - us\n\* `eu` - eu')
        .default(platformAlertsDestinationsCreateBodyPagerdutyRegionDefault)
        .describe('PagerDuty service region of the account. Used when type=pagerduty.\n\n\* `us` - us\n\* `eu` - eu'),
    event_kinds: zod
        .array(
            zod
                .enum(['firing', 'resolved', 'errored', 'broken'])
                .describe(
                    '\* `firing` - firing\n\* `resolved` - resolved\n\* `errored` - errored\n\* `broken` - broken'
                )
        )
        .min(1)
        .optional()
        .describe(
            "The alert transitions to send about. Defaults to every kind, or to firing and resolved for PagerDuty, which then hears each incident's trigger and resolve."
        ),
})

/**
 * Delete notification destinations of an alert.
 */
export const platformAlertsDestinationsDeleteCreateBodyDestinationIdsMax = 100

export const PlatformAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    destination_ids: zod
        .array(zod.uuid())
        .min(1)
        .max(platformAlertsDestinationsDeleteCreateBodyDestinationIdsMax)
        .describe('IDs of the destinations to delete, as the list endpoint returns them.'),
})

/**
 * @summary Snooze a whole alert
 */
export const PlatformAlertsSnoozeCreateBody = /* @__PURE__ */ zod.object({
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe(
            "Time until which every group's notifications are muted. Must be in the future and at most 30 days away. Null clears the snooze. The alert keeps being checked."
        ),
})

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
