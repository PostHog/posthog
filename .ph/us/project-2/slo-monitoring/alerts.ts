import { alert, destination, ref } from '@posthog/sdk/define'

import { alertFiringBlocks, hog, postToSlack, slackTemplate } from '../shared/slack'
import { team } from './config'
import { alertDeliveryFailureRate, regression } from './insights'

export const alertDeliverySlo = Object.entries(alertDeliveryFailureRate).map(([region, failureRate]) =>
    alert(`alert_delivery_slo_${region.toLowerCase()}`, {
        name: `Alert notification delivery SLO breach (${region})`,
        enabled: true,
        calculation_interval: 'daily',
        condition: { type: 'absolute_value' },
        threshold: { configuration: { type: 'absolute', bounds: { upper: 0.0005 } } },
        config: { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: false },
        insight: failureRate,
        subscribed_users: team.alertSubscribedUserIds,
    })
)

export const sloRegression = alert('slo_regression', {
    name: 'SLO regression: daily burn rate > 3x baseline',
    enabled: true,
    calculation_interval: 'daily',
    condition: { type: 'absolute_value' },
    threshold: { configuration: { type: 'absolute', bounds: { upper: 3 } } },
    config: { type: 'HogQLAlertConfig', evaluation: 'any_row', column: 'regression_ratio', label_column: 'operation' },
    insight: regression,
    subscribed_users: team.alertSubscribedUserIds,
})

export const sloRegressionSlack = destination('slo_regression_slack', {
    name: 'Post SLO regression alert to #alerts-product-analytics',
    description: 'Post to a Slack channel when the SLO regression alert fires',
    type: 'internal_destination',
    enabled: true,
    hog: postToSlack,
    inputs: {
        text: hog('Alert triggered: {event.properties.insight_name}'),
        blocks: hog(alertFiringBlocks),
        // #alerts-product-analytics
        channel: hog('C05G937QY1Z'),
        username: hog('SLO-monitor'),
        icon_emoji: hog(':hogzilla:'),
        slack_workspace: hog(team.slackWorkspaceId),
    },
    filters: {
        source: 'events',
        events: [{ id: '$insight_alert_firing', type: 'events' }],
        properties: [{ key: 'alert_id', type: 'event', value: ref(sloRegression), operator: 'exact' }],
    },
    ...slackTemplate,
})
