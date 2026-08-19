import type { SettingEnumApi } from '~/generated/core/api.schemas'

export type NotificationRuleValue = 'none' | 'on' | 'off'

export type NotificationConcept = {
    /** Typed against the generated enum, so a setting the API refuses cannot be listed here. */
    setting: SettingEnumApi
    label: string
    description: string
    /** Settings that break down by project are governed per project, the rest per person. */
    perProject: boolean
    /** True when the stored value means "disabled", so the control reads inverted. */
    inverse?: boolean
    /** Shown where a setting has no project dimension to offer. */
    note?: string
}

const NO_PROJECT_NOTE = 'PostHog stores this one as a single value per person, so it cannot be set per project.'

/**
 * Kept in step with `LOCKABLE_NOTIFICATION_SETTINGS` in
 * `posthog/models/organization_notification_lock.py`, which is what the API accepts.
 */
export const NOTIFICATION_CONCEPTS: NotificationConcept[] = [
    {
        setting: 'pipeline_notifications_disabled',
        label: 'Data pipeline errors',
        description: 'Emails when destinations, batch exports, or transformations fail.',
        perProject: true,
        inverse: true,
    },
    {
        setting: 'project_weekly_digest_disabled',
        label: 'Weekly digest',
        description: 'A weekly summary of what happened in a project.',
        perProject: true,
        inverse: true,
    },
    {
        setting: 'error_tracking_weekly_digest_project_enabled',
        label: 'Error tracking weekly digest',
        description: 'A weekly summary of exceptions caught in a project.',
        perProject: true,
    },
    {
        setting: 'web_analytics_weekly_digest_project_enabled',
        label: 'Web analytics weekly digest',
        description: 'A weekly summary of web traffic in a project.',
        perProject: true,
    },
    {
        setting: 'error_tracking_issue_assigned',
        label: 'Issue assigned',
        description: 'An email when an error tracking issue is assigned to them.',
        perProject: false,
        note: NO_PROJECT_NOTE,
    },
    {
        setting: 'discussions_mentioned',
        label: 'Comment mentions',
        description: 'An email when someone mentions them in a discussion.',
        perProject: false,
        note: NO_PROJECT_NOTE,
    },
    {
        setting: 'organization_member_join_email_disabled',
        label: 'New member joined',
        description: 'An email when someone joins the organization.',
        perProject: false,
        inverse: true,
    },
    {
        setting: 'materialized_view_sync_failed',
        label: 'Materialized view sync failures',
        description: 'Emails when a materialized view fails to sync.',
        perProject: false,
        note: NO_PROJECT_NOTE,
    },
    {
        setting: 'materialized_view_sync_failed_daily',
        label: 'Materialized view failures, daily digest',
        description: 'One email a day listing every failing view. Applies to people receiving the failures.',
        perProject: false,
    },
    {
        setting: 'materialized_view_sync_failed_immediate',
        label: 'Materialized view failures, right away',
        description: 'An email each time a view starts failing. Applies to people receiving the failures.',
        perProject: false,
    },
]

/**
 * The stored form of a rule. Some settings are stored as "disabled", so a rule that turns a
 * notification on stores `false`. This is the only place that knows which way round each is.
 */
export function storedValueFor(concept: NotificationConcept, value: 'on' | 'off'): boolean {
    const on = value === 'on'
    return concept.inverse ? !on : on
}

export function ruleValueFor(concept: NotificationConcept, stored: boolean): 'on' | 'off' {
    const on = concept.inverse ? !stored : stored
    return on ? 'on' : 'off'
}
