import { alert, destination, insight, type InsightDefinition, type InsightInput } from '@posthog/sdk/define'

import { alertFiringBlocks, hog, postToSlack, slackTemplate } from '../shared/slack'
import { analyticsPlatform, tags } from '../shared/teams'

type Region = 'us' | 'eu'

const exportRegions: Record<Region, { table: string; otherDashboards: number[]; unknownErrors: string }> = {
    us: {
        table: 'postgres.posthog_exportedasset',
        otherDashboards: [633001, 567706],
        unknownErrors: 'https://metabase.prod-us.posthog.dev/question/1838-analyse-unknown-exportedasset-exceptions',
    },
    eu: {
        table: 'eu_posthog_exportedasset',
        otherDashboards: [],
        unknownErrors: 'https://metabase.prod-eu.posthog.dev/question/565-analyse-unknown-exportedasset-exceptions',
    },
}

// Each series counts exported assets in the region's table, filtered by one outcome.
const outcomes: [string, string | null][] = [
    ['Starts', null],
    ['Success', 'export_context is not null or content_location is not null'],
    ['Caught Exceptions', 'exception is not null'],
    ['User failures', "failure_type = 'user'"],
    ['System failures', "failure_type = 'system'"],
    ['Timeout failures', "failure_type = 'timeout_generation'"],
    ['Unknown failures', "failure_type = 'unknown'"],
    [
        'Uncaught Exceptions',
        'exception is null and export_context is null and content_location is null and timestamp < now() - interval 10 minute',
    ],
]

function exportQuery(table: string): InsightInput['query'] {
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: outcomes.map(([name, condition]) => ({
                id: table,
                kind: 'DataWarehouseNode',
                math: 'total',
                name: table,
                id_field: 'id',
                ...(condition ? { properties: [{ key: condition, type: 'hogql', value: null }] } : {}),
                table_name: table,
                custom_name: name,
                timestamp_field: 'created_at',
                distinct_id_field: 'created_by_id',
            })),
            version: 2,
            properties: [],
            trendsFilter: {
                display: 'ActionsLineGraph',
                formulaNodes: [
                    { formula: 'B/A', custom_name: 'Success' },
                    { formula: 'C/A', custom_name: 'Caught' },
                    { formula: 'H/A', custom_name: 'Uncaught' },
                    { formula: 'D/A', custom_name: 'User Errors' },
                    { formula: 'E/A', custom_name: 'System Errors' },
                    { formula: 'F/A', custom_name: 'Timeout Errors' },
                    { formula: 'G/A', custom_name: 'Unknown Errors' },
                ],
                decimalPlaces: 4,
                yAxisScaleType: 'log10',
                showMultipleYAxes: false,
                showValuesOnSeries: true,
                aggregationAxisFormat: 'percentage_scaled',
                showAlertThresholdLines: true,
            },
            breakdownFilter: null,
        },
    }
}

export const exportResults: Record<Region, InsightDefinition> = {
    us: exportInsight('us'),
    eu: exportInsight('eu'),
}

function exportInsight(region: Region): InsightDefinition {
    const { table, otherDashboards, unknownErrors } = exportRegions[region]
    return insight(`export_successes_and_failures_${region}`, {
        name: `Export Successes and Failures (${region.toUpperCase()})`,
        query: exportQuery(table),
        tags: [tags.managed],
        ...(otherDashboards.length > 0 ? { dashboards: otherDashboards } : {}),
        description: `More details about the unknown errors can be found here: ${unknownErrors}`,
    })
}

// The same checks for each region. A series index points at the export insight's series above.
const exportAlerts: { key: string; name: string; lower?: number; upper?: number; series: number }[] = [
    { key: 'decrease_in_success_rate', name: 'Decrease in success rate for exports', lower: 0.99, series: 0 },
    { key: 'timeout_spike', name: 'Timeout spike', upper: 0.03, series: 5 },
    { key: 'system_error_spike', name: 'System error spike', upper: 0.03, series: 4 },
    { key: 'user_error_spike', name: 'User error spike', upper: 0.03, series: 3 },
    { key: 'unknown_alert_spike', name: 'Unknown alert spike', upper: 0.01, series: 6 },
]

export const exportAlertsByRegion = (['us', 'eu'] as const).flatMap((region) =>
    exportAlerts.map(({ key, name, lower, upper, series }) => {
        const check = alert(`${key}_${region}`, {
            name: `${name} (${region.toUpperCase()})`,
            enabled: true,
            calculation_interval: 'daily',
            condition: { type: 'absolute_value' },
            threshold: {
                configuration: {
                    type: 'absolute',
                    bounds: { ...(lower !== undefined ? { lower } : {}), ...(upper !== undefined ? { upper } : {}) },
                },
            },
            config: { type: 'TrendsAlertConfig', series_index: series, check_ongoing_interval: false },
            insight: exportResults[region],
            subscribed_users: analyticsPlatform.alertSubscribedUserIds,
        })
        // One Slack destination per alert, filtered to that alert's firing events.
        const notification = destination(`slack_alert_notification-${key}_${region}`, {
            name: 'Post to Slack on insight alert firing',
            description: 'Post to a Slack channel when this insight alert fires',
            type: 'internal_destination',
            enabled: true,
            hog: postToSlack,
            inputs: {
                text: hog('Alert triggered: {event.properties.insight_name}'),
                blocks: hog(alertFiringBlocks),
                channel: hog(analyticsPlatform.slackChannelId),
                username: hog('Export-monitor'),
                icon_emoji: hog(':hogzilla:'),
                slack_workspace: hog(analyticsPlatform.slackWorkspaceId),
            },
            filters: {
                source: 'events',
                events: [{ id: '$insight_alert_firing', type: 'events' }],
                properties: [{ key: 'alert_id', type: 'event', value: check, operator: 'exact' }],
            },
            ...slackTemplate,
        })
        return { alert: check, notification }
    })
)
