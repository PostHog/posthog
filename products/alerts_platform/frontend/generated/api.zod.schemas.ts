/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const PlatformAlertConfigurationSourceKindEnumApi = zod.enum(['logs']).describe('\* `logs` - Logs')

export type PlatformAlertConfigurationSourceKindEnumApi = zod.input<typeof PlatformAlertConfigurationSourceKindEnumApi>
export type PlatformAlertConfigurationSourceKindEnumApiOutput = zod.output<
    typeof PlatformAlertConfigurationSourceKindEnumApi
>

export const CalendarUnitEnumApi = zod
    .enum(['day', 'week', 'month'])
    .describe('\* `day` - Day\n\* `week` - Week\n\* `month` - Month')

export type CalendarUnitEnumApi = zod.input<typeof CalendarUnitEnumApi>
export type CalendarUnitEnumApiOutput = zod.output<typeof CalendarUnitEnumApi>

export const AlertScheduleRestrictionWindowApi = zod.object({
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

export type AlertScheduleRestrictionWindowApi = zod.input<typeof AlertScheduleRestrictionWindowApi>
export type AlertScheduleRestrictionWindowApiOutput = zod.output<typeof AlertScheduleRestrictionWindowApi>

export const AlertScheduleRestrictionApi = zod.object({
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
})

export type AlertScheduleRestrictionApi = zod.input<typeof AlertScheduleRestrictionApi>
export type AlertScheduleRestrictionApiOutput = zod.output<typeof AlertScheduleRestrictionApi>

export const BillingAlertConfigurationStateEnumApi = zod
    .enum(['not_firing', 'firing', 'errored', 'snoozed', 'broken'])
    .describe(
        '\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
    )

export type BillingAlertConfigurationStateEnumApi = zod.input<typeof BillingAlertConfigurationStateEnumApi>
export type BillingAlertConfigurationStateEnumApiOutput = zod.output<typeof BillingAlertConfigurationStateEnumApi>

export const PlatformAlertApi = zod.object({
    id: zod.uuid().describe('Unique identifier of this alert instance.'),
    grouping_key: zod
        .string()
        .describe('Key of the result group this instance tracks. Empty when the source does not group results.'),
    state: zod
        .enum(['not_firing', 'firing', 'errored', 'snoozed', 'broken'])
        .describe(
            '\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
        )
        .describe(
            'Current state of this alert instance.\n\n\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
        ),
    firing_started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the current firing started. Null when the instance is not firing.'),
    last_notified_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When a notification was last sent for this instance.'),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Time until which notifications are snoozed. Null when not snoozed.'),
})

export type PlatformAlertApi = zod.input<typeof PlatformAlertApi>
export type PlatformAlertApiOutput = zod.output<typeof PlatformAlertApi>

export const PlatformAlertConfigurationApi = zod.object({
    id: zod.uuid().describe('Unique identifier of the alert configuration.'),
    name: zod.string().describe('Human-readable name of the alert.'),
    enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
    source_kind: zod
        .enum(['logs'])
        .describe('\* `logs` - Logs')
        .describe('Product whose data the alert evaluates.\n\n\* `logs` - Logs'),
    source_config: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Source-specific settings. The shape depends on source_kind. The bound the alert is evaluated against is under the condition key.'
        ),
    check_interval_minutes: zod
        .number()
        .describe('Minutes between scheduled checks. Applies when recurrence_unit is null.'),
    recurrence_unit: zod
        .union([
            zod.enum(['day', 'week', 'month']).describe('\* `day` - Day\n\* `week` - Week\n\* `month` - Month'),
            zod.null(),
        ])
        .describe(
            'Calendar unit the alert recurs on. Null means it recurs on check_interval_minutes.\n\n\* `day` - Day\n\* `week` - Week\n\* `month` - Month'
        ),
    anchor_time: zod
        .string()
        .nullable()
        .describe(
            'Local time (HH:MM in the project timezone) a calendar recurrence lands on. Null means the default anchor for the unit.'
        ),
    evaluation_periods: zod.number().describe('Number of recent checks considered when deciding to fire.'),
    datapoints_to_alarm: zod
        .number()
        .describe('Number of breaching checks within evaluation_periods required to fire.'),
    cooldown_minutes: zod.number().describe('Minimum minutes between notifications for the same alert.'),
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
            'Blocked local time windows (HH:MM in the project timezone) when the alert does not run. Null means no quiet hours.'
        ),
    next_check_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the next check is due. Null when no check is scheduled.'),
    consecutive_failures: zod.number().describe('Number of checks in a row that failed to evaluate.'),
    legacy_configuration_id: zod
        .uuid()
        .nullable()
        .describe(
            'ID of the legacy source configuration this row was backfilled from. Null for alerts created on the platform.'
        ),
    created_at: zod.iso.datetime({ offset: true }).describe('When the configuration was created.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the configuration was last changed.'),
    alerts: zod
        .array(
            zod.object({
                id: zod.uuid().describe('Unique identifier of this alert instance.'),
                grouping_key: zod
                    .string()
                    .describe(
                        'Key of the result group this instance tracks. Empty when the source does not group results.'
                    ),
                state: zod
                    .enum(['not_firing', 'firing', 'errored', 'snoozed', 'broken'])
                    .describe(
                        '\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
                    )
                    .describe(
                        'Current state of this alert instance.\n\n\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
                    ),
                firing_started_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When the current firing started. Null when the instance is not firing.'),
                last_notified_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When a notification was last sent for this instance.'),
                snooze_until: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('Time until which notifications are snoozed. Null when not snoozed.'),
            })
        )
        .describe('Runtime state for each result group of this configuration.'),
})

export type PlatformAlertConfigurationApi = zod.input<typeof PlatformAlertConfigurationApi>
export type PlatformAlertConfigurationApiOutput = zod.output<typeof PlatformAlertConfigurationApi>

export const PaginatedPlatformAlertConfigurationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('Unique identifier of the alert configuration.'),
            name: zod.string().describe('Human-readable name of the alert.'),
            enabled: zod.boolean().describe('Whether the alert is evaluated on schedule.'),
            source_kind: zod
                .enum(['logs'])
                .describe('\* `logs` - Logs')
                .describe('Product whose data the alert evaluates.\n\n\* `logs` - Logs'),
            source_config: zod
                .record(zod.string(), zod.unknown())
                .describe(
                    'Source-specific settings. The shape depends on source_kind. The bound the alert is evaluated against is under the condition key.'
                ),
            check_interval_minutes: zod
                .number()
                .describe('Minutes between scheduled checks. Applies when recurrence_unit is null.'),
            recurrence_unit: zod
                .union([
                    zod.enum(['day', 'week', 'month']).describe('\* `day` - Day\n\* `week` - Week\n\* `month` - Month'),
                    zod.null(),
                ])
                .describe(
                    'Calendar unit the alert recurs on. Null means it recurs on check_interval_minutes.\n\n\* `day` - Day\n\* `week` - Week\n\* `month` - Month'
                ),
            anchor_time: zod
                .string()
                .nullable()
                .describe(
                    'Local time (HH:MM in the project timezone) a calendar recurrence lands on. Null means the default anchor for the unit.'
                ),
            evaluation_periods: zod.number().describe('Number of recent checks considered when deciding to fire.'),
            datapoints_to_alarm: zod
                .number()
                .describe('Number of breaching checks within evaluation_periods required to fire.'),
            cooldown_minutes: zod.number().describe('Minimum minutes between notifications for the same alert.'),
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
                    'Blocked local time windows (HH:MM in the project timezone) when the alert does not run. Null means no quiet hours.'
                ),
            next_check_at: zod.iso
                .datetime({ offset: true })
                .nullable()
                .describe('When the next check is due. Null when no check is scheduled.'),
            consecutive_failures: zod.number().describe('Number of checks in a row that failed to evaluate.'),
            legacy_configuration_id: zod
                .uuid()
                .nullable()
                .describe(
                    'ID of the legacy source configuration this row was backfilled from. Null for alerts created on the platform.'
                ),
            created_at: zod.iso.datetime({ offset: true }).describe('When the configuration was created.'),
            updated_at: zod.iso.datetime({ offset: true }).describe('When the configuration was last changed.'),
            alerts: zod
                .array(
                    zod.object({
                        id: zod.uuid().describe('Unique identifier of this alert instance.'),
                        grouping_key: zod
                            .string()
                            .describe(
                                'Key of the result group this instance tracks. Empty when the source does not group results.'
                            ),
                        state: zod
                            .enum(['not_firing', 'firing', 'errored', 'snoozed', 'broken'])
                            .describe(
                                '\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
                            )
                            .describe(
                                'Current state of this alert instance.\n\n\* `not_firing` - Not firing\n\* `firing` - Firing\n\* `errored` - Errored\n\* `snoozed` - Snoozed\n\* `broken` - Broken'
                            ),
                        firing_started_at: zod.iso
                            .datetime({ offset: true })
                            .nullable()
                            .describe('When the current firing started. Null when the instance is not firing.'),
                        last_notified_at: zod.iso
                            .datetime({ offset: true })
                            .nullable()
                            .describe('When a notification was last sent for this instance.'),
                        snooze_until: zod.iso
                            .datetime({ offset: true })
                            .nullable()
                            .describe('Time until which notifications are snoozed. Null when not snoozed.'),
                    })
                )
                .describe('Runtime state for each result group of this configuration.'),
        })
    ),
})

export type PaginatedPlatformAlertConfigurationListApi = zod.input<typeof PaginatedPlatformAlertConfigurationListApi>
export type PaginatedPlatformAlertConfigurationListApiOutput = zod.output<
    typeof PaginatedPlatformAlertConfigurationListApi
>
