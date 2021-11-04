import React from 'react'
import { AnnotationScope } from '../types'

// Sync these with the ChartDisplayType enum in types.ts
// ... and remove once all files have migrated to TypeScript
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

export enum TeamMembershipLevel {
    Member = 1,
    Admin = 8,
}

/** See posthog/api/organization.py for details. */
export enum PluginsAccessLevel {
    None = 0,
    Config = 3,
    Install = 6,
    Root = 9,
}

export const annotationScopeToName = new Map<string, string>([
    [AnnotationScope.DashboardItem, 'dashboard item'],
    [AnnotationScope.Project, 'project'],
    [AnnotationScope.Organization, 'organization'],
])

export const PERSON_DISTINCT_ID_MAX_SIZE = 3

// Event constants
export const ACTION_TYPE = 'action_type'
export const EVENT_TYPE = 'event_type'

// TODO: Deprecated; should be removed once backend is updated
export enum ShownAsValue {
    VOLUME = 'Volume',
    STICKINESS = 'Stickiness',
    LIFECYCLE = 'Lifecycle',
}

// Retention constants
export const RETENTION_RECURRING = 'retention_recurring'
export const RETENTION_FIRST_TIME = 'retention_first_time'

// Properties constants
export const PROPERTY_MATH_TYPE = 'property'
export const EVENT_MATH_TYPE = 'event'
export const MATHS: Record<string, any> = {
    total: {
        name: 'Total count',
        description: (
            <>
                Total event count. Total number of times the event was performed by any user.
                <br />
                <br />
                <i>Example: If a user performs an event 3 times in the given period, it counts as 3.</i>
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    dau: {
        name: 'Unique users',
        description: (
            <>
                Number of unique users who performed the event in the specified period.
                <br />
                <br />
                <i>
                    Example: If a single user performs an event 3 times in a given day/week/month, it counts only as 1.
                </i>
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    weekly_active: {
        name: 'Weekly active',
        description: (
            <>
                Users active in the past week (7 days).
                <br />
                This is a trailing count that aggregates distinct users in the past 7 days for each day in the time
                series
            </>
        ),
        onProperty: false,
        type: EVENT_MATH_TYPE,
    },
    monthly_active: {
        name: 'Monthly active',
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
    avg: {
        name: 'Average',
        description: (
            <>
                Average of a property value within an event or action.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 14.
            </>
        ),
        onProperty: true,
        type: PROPERTY_MATH_TYPE,
    },
    sum: {
        name: 'Sum',
        description: (
            <>
                Sum of property values within an event or action.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 42.
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

export const FEATURE_FLAGS = {
    // Cloud-only
    CLOUD_ANNOUNCEMENT: 'cloud-announcement',
    NPS_PROMPT: '4562-nps', // owner: @paolodamico
    // Experiments / beta features
    INGESTION_GRID: 'ingestion-grid-exp-3', // owner: @kpthatsme
    TRAILING_WAU_MAU: '3638-trailing-wau-mau', // owner: @EDsCODE
    EVENT_COLUMN_CONFIG: '4141-event-columns', // owner: @pauldambra
    SAVED_INSIGHTS: '3408-saved-insights', // owner: @alexkim
    MULTIVARIATE_SUPPORT: '5440-multivariate-support', // owner: @mariusandra
    FUNNEL_HORIZONTAL_UI: '5730-funnel-horizontal-ui', // owner: @alexkim
    DIVE_DASHBOARDS: 'hackathon-dive-dashboards', // owner: @tiina303
    NEW_PATHS_UI: 'new-paths-ui', // owner: @EDsCODE
    NEW_PATHS_UI_EDGE_WEIGHTS: 'new-paths-ui-edge-weights', // owner: @neilkakkar
    REMOVE_SESSIONS: '6050-remove-sessions', // owner: @rcmarron
    FUNNEL_VERTICAL_BREAKDOWN: '5733-funnel-vertical-breakdown', // owner: @alexkim
    RENAME_FILTERS: '6063-rename-filters', // owner: @alexkim
    CORRELATION_ANALYSIS: 'correlation-analysis', // owner: @neilkakkar
    SIGMA_ANALYSIS: 'sigma-analysis', // owner: @neilkakkar
    NEW_SESSIONS_PLAYER: 'new-sessions-player', // owner: @rcmarron
    BREAKDOWN_BY_MULTIPLE_PROPERTIES: '938-breakdown-by-multiple-properties', // owner: @pauldambra
    LEMONADE: '5346-lemonade', // owner: @Twixes
    TURBO_MODE: 'turbo-mode', // owner: @mariusandra
}

export const ENTITY_MATCH_TYPE = 'entities'
export const PROPERTY_MATCH_TYPE = 'properties'

export enum FunnelLayout {
    horizontal = 'horizontal',
    vertical = 'vertical',
}

export const BinCountAuto = 'auto'

export const ERROR_MESSAGES: Record<string, string> = {
    no_new_organizations:
        'Your email address is not associated with an account. Please ask your administrator for an invite.',
}

// Cohort types
export const COHORT_STATIC = 'static'
export const COHORT_DYNAMIC = 'dynamic'

/**
 * Mock Node.js `process`, which is required by VFile that is used by ReactMarkdown.
 * See https://github.com/remarkjs/react-markdown/issues/339.
 */
export const MOCK_NODE_PROCESS = { cwd: () => '', env: {} } as unknown as NodeJS.Process
