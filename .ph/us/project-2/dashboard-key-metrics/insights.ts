import { hogql, insight } from '@posthog/sdk/define'

// The dashboard's insights as PostHog holds them, written out from what the team built in the UI.
// The dashboard adds itself to each insight's dashboards; the ids here are other teams' dashboards.

export const alertCreation = insight('alert_creation', {
    name: 'Alert creation',
    tags: ['managed-by:terraform'],
    query: {
        kind: 'InsightVizNode',
        source: {
            breakdownFilter: null,
            dateRange: {
                date_from: '-30d',
                date_to: null,
                explicitDate: false,
            },
            interval: 'day',
            kind: 'TrendsQuery',
            properties: [],
            series: [
                {
                    custom_name: 'Unique users',
                    distinct_id_field: 'created_by_id',
                    id: 'postgres.posthog_alertconfiguration',
                    id_field: 'id',
                    kind: 'DataWarehouseNode',
                    math: 'dau',
                    name: 'postgres.posthog_alertconfiguration',
                    table_name: 'postgres.posthog_alertconfiguration',
                    timestamp_field: 'created_at',
                },
                {
                    custom_name: 'Total count',
                    distinct_id_field: 'created_by_id',
                    id: 'postgres.posthog_alertconfiguration',
                    id_field: 'id',
                    kind: 'DataWarehouseNode',
                    math: 'total',
                    name: 'postgres.posthog_alertconfiguration',
                    table_name: 'postgres.posthog_alertconfiguration',
                    timestamp_field: 'created_at',
                },
            ],
            trendsFilter: {
                showLegend: true,
            },
            version: 2,
        },
    },
})

export const alertFailuresByExceptionTypeAggregated = insight('alert_failures_by_exception_type_aggregated', {
    name: 'Alert failures by exception type (aggregated)',
    description:
        'Failures grouped by exception type with alert IDs normalized, showing the core issues affecting alerts',
    tags: ['managed-by:terraform'],
    dashboards: [1142938, 821321, 1294240],
    query: {
        kind: 'DataTableNode',
        source: {
            kind: 'HogQLQuery',
            query: `SELECT
  coalesce(
    properties.error_type,
    if(properties.alert_state = 'Errored', 'Alert configuration error', 'Unknown error')
  ) AS exception_type,
  count() AS failure_count,
  count() * 100.0 / sum(count()) OVER () AS percentage_of_failures,
  uniq(properties.resource_id) AS unique_alerts_affected,
  uniq(properties.team_id) AS unique_teams_affected,
  min(timestamp) AS first_occurrence,
  max(timestamp) AS last_occurrence
FROM events
WHERE event = 'slo_operation_completed'
  AND properties.operation = 'alert_check'
  AND (properties.outcome = 'failure' OR properties.alert_state = 'Errored')
  AND timestamp >= now() - INTERVAL 30 DAY
  AND timestamp < now()
GROUP BY exception_type
ORDER BY failure_count DESC
LIMIT 100`,
        },
    },
})

export const apiCallsOriginatingFromOurTerraformProvider = insight(
    'api_calls_originating_from_our_terraform_provider',
    hogql({
        name: 'API calls originating from our Terraform Provider',
        tags: ['managed-by:terraform'],
        dashboards: [821321],
        query: `SELECT 
    extract(properties.$user_agent, 'version: ([0-9\\\\.\\\\-a-zA-Z]+)') as version,
    person.properties.email as email,
    person.properties.org__name as organization,
    count() as api_calls,
    min(timestamp) as first_call,
    max(timestamp) as last_call
FROM events
WHERE 
    properties.$user_agent LIKE '%terraform-provider%'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY version, email, organization
ORDER BY api_calls DESC`,
        chartSettings: {
            xAxis: {
                column: 'first_call',
            },
            yAxis: [
                {
                    column: 'api_calls',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
            ],
        },
        display: 'ActionsTable',
        tableSettings: {
            columns: [
                {
                    column: 'version',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    column: 'email',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    column: 'organization',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    column: 'api_calls',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    column: 'first_call',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    column: 'last_call',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
            ],
        },
    })
)

export const createdSubscriptions = insight('created_subscriptions', {
    name: 'Created subscriptions',
    tags: ['managed-by:terraform'],
    query: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    event: 'dashboard subscription created',
                    kind: 'EventsNode',
                    math: 'total',
                    name: 'dashboard subscription created',
                },
                {
                    event: 'insight subscription created',
                    kind: 'EventsNode',
                    math: 'total',
                    name: 'insight subscription created',
                },
            ],
            trendsFilter: {
                showLegend: true,
            },
            version: 2,
        },
    },
})

export const dashboardCreatedUniqueUsersByEventSSource = insight('dashboard_created_unique_users_by_event_s_source', {
    tags: ['managed-by:terraform'],
    derived_name: "dashboard created unique users by event's source",
    query: {
        kind: 'InsightVizNode',
        source: {
            breakdownFilter: {
                breakdowns: [
                    {
                        property: 'source',
                        type: 'event',
                    },
                ],
            },
            filterTestAccounts: true,
            kind: 'TrendsQuery',
            series: [
                {
                    event: 'dashboard created',
                    kind: 'EventsNode',
                    math: 'dau',
                    name: 'dashboard created',
                },
            ],
            trendsFilter: {
                display: 'ActionsAreaGraph',
            },
            version: 2,
        },
    },
})

export const dashboardsCreatedFromTemplateUniqueUsers = insight('dashboards_created_from_template_unique_users', {
    name: 'Dashboards created from template (unique users)',
    tags: ['managed-by:terraform'],
    dashboards: [778670],
    query: {
        kind: 'InsightVizNode',
        source: {
            dateRange: {
                date_from: '-30d',
            },
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            properties: [],
            series: [
                {
                    custom_name: 'Dashboard created from template (unique users)',
                    event: 'dashboard created',
                    kind: 'EventsNode',
                    math: 'dau',
                    properties: [
                        {
                            key: 'from_template',
                            operator: 'exact',
                            type: 'event',
                            value: 'true',
                        },
                    ],
                },
                {
                    custom_name: 'Dashboard created (unique users)',
                    event: 'dashboard created',
                    kind: 'EventsNode',
                    math: 'dau',
                },
            ],
            trendsFilter: {
                aggregationAxisFormat: 'percentage',
                display: 'ActionsLineGraph',
                formulaNodes: [
                    {
                        formula: '(A/B) * 100',
                    },
                ],
                showLegend: true,
                showPercentStackView: false,
                showValuesOnSeries: false,
                yAxisScaleType: 'linear',
            },
            version: 2,
        },
    },
})

export const sharedDashboardStats = insight('shared_dashboard_stats', {
    name: 'Shared Dashboard Stats',
    tags: ['managed-by:terraform'],
    query: {
        kind: 'InsightVizNode',
        showHeader: true,
        source: {
            breakdownFilter: null,
            compareFilter: null,
            dateRange: {
                date_from: '-30d',
                date_to: null,
            },
            filterTestAccounts: true,
            interval: 'day',
            kind: 'TrendsQuery',
            properties: [],
            samplingFactor: null,
            series: [
                {
                    event: 'viewed dashboard',
                    kind: 'EventsNode',
                    math: 'total',
                    math_group_type_index: null,
                    math_property: null,
                    math_property_type: null,
                    properties: [
                        {
                            key: 'is_shared',
                            operator: 'exact',
                            type: 'event',
                            value: 'true',
                        },
                    ],
                },
                {
                    event: 'dashboard share toggled',
                    kind: 'EventsNode',
                    math: 'total',
                    name: 'dashboard share toggled',
                    properties: [
                        {
                            key: 'is_shared',
                            operator: 'exact',
                            type: 'event',
                            value: ['true'],
                        },
                    ],
                },
            ],
            trendsFilter: {
                aggregationAxisFormat: 'numeric',
                aggregationAxisPostfix: null,
                aggregationAxisPrefix: null,
                decimalPlaces: null,
                display: 'ActionsLineGraph',
                formulas: null,
                showLegend: false,
                showPercentStackView: false,
                showValuesOnSeries: false,
                yAxisScaleType: 'linear',
            },
            version: 2,
        },
    },
})

export const usageByRole = insight('usage_by_role', {
    name: 'Usage by role',
    tags: ['managed-by:terraform'],
    query: {
        kind: 'InsightVizNode',
        source: {
            breakdownFilter: {
                breakdowns: [
                    {
                        property: 'role_at_organization',
                        type: 'person',
                    },
                ],
            },
            dateRange: {
                date_from: '-90d',
                date_to: null,
                explicitDate: false,
            },
            filterTestAccounts: true,
            interval: 'week',
            kind: 'TrendsQuery',
            series: [
                {
                    id: '214129',
                    kind: 'ActionsNode',
                    math: 'total',
                    name: '[team-analytics-platform] Clicked New action in data management',
                },
            ],
            trendsFilter: {
                display: 'ActionsAreaGraph',
            },
            version: 2,
        },
    },
})
