import React from 'react'

export const ACTIONS_LINE_GRAPH_LINEAR = 'ActionsLineGraph'
export const ACTIONS_LINE_GRAPH_CUMULATIVE = 'ActionsLineGraphCumulative'
export const ACTIONS_TABLE = 'ActionsTable'
export const ACTIONS_PIE_CHART = 'ActionsPie'
export const ACTIONS_BAR_CHART = 'ActionsBar'
export const ACTIONS_BAR_CHART_VALUE = 'ActionsBarValue'
export const PATHS_VIZ = 'PathsViz'
export const FUNNEL_VIZ = 'FunnelViz'

export enum OrganizationMembershipLevel {
    Member = 1,
    Admin = 8,
    Owner = 15,
}

/** See posthog/api/organization.py for details. */
export enum PluginsAccessLevel {
    None = 0,
    Config = 3,
    Install = 6,
    Root = 9,
}

export const organizationMembershipLevelToName = new Map<number, string>([
    [OrganizationMembershipLevel.Member, 'member'],
    [OrganizationMembershipLevel.Admin, 'administrator'],
    [OrganizationMembershipLevel.Owner, 'owner'],
])

export enum AnnotationScope {
    DashboardItem = 'dashboard_item',
    Project = 'project',
    Organization = 'organization',
}

export const annotationScopeToName = new Map<string, string>([
    [AnnotationScope.DashboardItem, 'dashboard item'],
    [AnnotationScope.Project, 'project'],
    [AnnotationScope.Organization, 'organization'],
])

export const PERSON_DISTINCT_ID_MAX_SIZE = 3

export const PAGEVIEW = '$pageview'
export const AUTOCAPTURE = '$autocapture'
export const SCREEN = '$screen'
export const CUSTOM_EVENT = 'custom_event'

export const ACTION_TYPE = 'action_type'
export const EVENT_TYPE = 'event_type'

export enum ShownAsValue {
    VOLUME = 'Volume',
    STICKINESS = 'Stickiness',
    LIFECYCLE = 'Lifecycle',
}

export const PROPERTY_MATH_TYPE = 'property'
export const EVENT_MATH_TYPE = 'event'

export const MATHS: Record<string, any> = {
    total: {
        name: 'Total volume',
        description: (
            <>
                Total event volume.
                <br />
                <br />
                If a user performs an event 3 times in a given day/week/month, it counts as 3.
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    dau: {
        name: 'Unique users',
        description: (
            <>
                Unique users who performed the event in the specified time interval.
                <br />
                <br />
                If a single user performs an event 3 times in a given day/week/month, it counts only as 1.
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    weekly_active: {
        name: 'Weekly Active',
        description: (
            <>
                Users active in the past week (7 days). This is a trailing count that aggregates distinct users in the
                past 7 days for each day in the time series
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    monthly_active: {
        name: 'Monthly Active',
        description: (
            <>
                Users active in the past month (30 days).
                <br />
                This is a trailing count that aggregates distinct users in the past 30 days for each day in the time
                series
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    sum: {
        name: 'Sum',
        description: (
            <>
                Event property sum.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 42.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    avg: {
        name: 'Average',
        description: (
            <>
                Event property average.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 14.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    min: {
        name: 'Minimum',
        description: (
            <>
                Event property minimum.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 10.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    max: {
        name: 'Maximum',
        description: (
            <>
                Event property maximum.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 20.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    median: {
        name: 'Median',
        description: (
            <>
                Event property median (50th percentile).
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 150.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    p90: {
        name: '90th percentile',
        description: (
            <>
                Event property 90th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 190.
            </>
        ),
        onProperty: true,
        type: 'property',
    },
    p95: {
        name: '95th percentile',
        description: (
            <>
                Event property 95th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 195.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    p99: {
        name: '99th percentile',
        description: (
            <>
                Event property 90th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 199.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
}

export const WEBHOOK_SERVICES: Record<string, string> = {
    Slack: 'slack.com',
    Discord: 'discord.com',
    Teams: 'office.com',
}

export const FEATURE_FLAGS: Record<string, string> = {
    INGESTION_GRID: 'ingestion-grid-exp-3',
}
