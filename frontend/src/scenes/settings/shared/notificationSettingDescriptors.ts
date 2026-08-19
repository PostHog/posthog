import type { SettingEnumApi } from '~/generated/core/api.schemas'

/**
 * What a setting's scope IDs refer to, which decides what the admin surface lists under it.
 * `none` means the setting is a single switch with no per-resource breakdown.
 */
export type NotificationScopeKind = 'none' | 'team' | 'organization' | 'pipeline'

export type NotificationSettingDescriptor = {
    /**
     * Typed against the generated enum, so a setting the API refuses to lock cannot be listed
     * here without failing the type check.
     */
    setting: SettingEnumApi
    label: string
    description: string
    scope: NotificationScopeKind
    /** True when the stored value means "disabled", so the control reads inverted. */
    inverse?: boolean
}

/**
 * The email notifications an organization admin can enforce, and what each one is scoped by.
 *
 * Kept in step with `LOCKABLE_NOTIFICATION_SETTINGS` in
 * `posthog/models/organization_notification_lock.py`, which is the list the API accepts. A setting
 * missing there is rejected on save even if it appears here.
 *
 * Security alerts are deliberately absent: an organization cannot take away a member's view of
 * their own account security.
 */
export const LOCKABLE_NOTIFICATION_SETTINGS: NotificationSettingDescriptor[] = [
    {
        setting: 'all_weekly_digest_disabled',
        label: 'Weekly digest',
        description: "A weekly summary of what happened across the organization's projects.",
        scope: 'none',
        inverse: true,
    },
    {
        setting: 'project_weekly_digest_disabled',
        label: 'Weekly digest, per project',
        description: 'Which projects the weekly digest covers.',
        scope: 'team',
        inverse: true,
    },
    {
        setting: 'organization_member_join_email_disabled',
        label: 'New member joined',
        description: 'An email when someone joins the organization.',
        scope: 'organization',
        inverse: true,
    },
    {
        setting: 'plugin_disabled',
        label: 'Data pipeline errors',
        description: 'Emails when destinations, batch exports, or transformations fail.',
        scope: 'none',
    },
    {
        setting: 'pipeline_notifications_disabled',
        label: 'Data pipeline errors, per pipeline',
        description: 'Which pipelines send failure emails.',
        scope: 'pipeline',
        inverse: true,
    },
    {
        setting: 'error_tracking_issue_assigned',
        label: 'Issue assigned',
        description: 'An email when an error tracking issue is assigned to them.',
        scope: 'none',
    },
    {
        setting: 'error_tracking_weekly_digest',
        label: 'Error tracking weekly digest',
        description: 'A weekly summary of exceptions caught across projects.',
        scope: 'none',
    },
    {
        setting: 'error_tracking_weekly_digest_project_enabled',
        label: 'Error tracking digest, per project',
        description: 'Which projects the error tracking digest covers.',
        scope: 'team',
    },
    {
        setting: 'web_analytics_weekly_digest',
        label: 'Web analytics weekly digest',
        description: 'A weekly summary of web traffic across projects.',
        scope: 'none',
    },
    {
        setting: 'web_analytics_weekly_digest_project_enabled',
        label: 'Web analytics digest, per project',
        description: 'Which projects the web analytics digest covers.',
        scope: 'team',
    },
    {
        setting: 'discussions_mentioned',
        label: 'Comment mentions',
        description: 'An email when someone mentions them in a discussion.',
        scope: 'none',
    },
    {
        setting: 'materialized_view_sync_failed',
        label: 'Materialized view sync failures',
        description: 'Emails when a materialized view fails to sync.',
        scope: 'none',
    },
    {
        setting: 'materialized_view_sync_failed_daily',
        label: 'Materialized view failures, daily digest',
        description: 'One email a day listing every failing view.',
        scope: 'none',
    },
    {
        setting: 'materialized_view_sync_failed_immediate',
        label: 'Materialized view failures, right away',
        description: 'An email each time a view starts failing.',
        scope: 'none',
    },
]

export const LOCKABLE_SETTING_KEYS = new Set<string>(
    LOCKABLE_NOTIFICATION_SETTINGS.map((descriptor) => descriptor.setting)
)

/** Defaults for settings that are absent from a member's stored preferences. */
const SETTING_DEFAULTS: Partial<Record<string, boolean>> = {
    plugin_disabled: true,
    error_tracking_issue_assigned: true,
    error_tracking_weekly_digest: true,
    web_analytics_weekly_digest: true,
    discussions_mentioned: true,
    all_weekly_digest_disabled: false,
    materialized_view_sync_failed: false,
    materialized_view_sync_failed_daily: true,
    materialized_view_sync_failed_immediate: false,
}

/**
 * The value to store for a control the admin ticked.
 *
 * Some settings are stored as "disabled", so a ticked box and a stored `true` are opposites. The
 * API and the send-time code read the stored form, the UI shows the member-facing form, and this
 * is the only place that knows which is which.
 */
export function checkedToStoredValue(descriptor: NotificationSettingDescriptor, checked: boolean): boolean {
    return descriptor.inverse ? !checked : checked
}

export function storedToCheckedValue(descriptor: NotificationSettingDescriptor, stored: boolean): boolean {
    return descriptor.inverse ? !stored : stored
}

/**
 * Whether a member receives this notification, before any lock applies.
 *
 * Returns the value as the member experiences it, so an inverted setting stored as "disabled"
 * comes back as "receives it".
 */
export function storedValueFor(
    settings: Record<string, any> | undefined,
    descriptor: NotificationSettingDescriptor,
    scopeId: string
): boolean {
    const raw = settings?.[descriptor.setting]
    const value =
        descriptor.scope === 'none'
            ? typeof raw === 'boolean'
                ? raw
                : SETTING_DEFAULTS[descriptor.setting]
            : (raw ?? {})[scopeId]

    if (value === undefined || value === null) {
        // An absent per-resource entry means the member is subscribed for opt-out settings, and
        // not yet configured for opt-in ones.
        return descriptor.scope === 'none' ? false : !!descriptor.inverse
    }
    return descriptor.inverse ? !value : !!value
}
