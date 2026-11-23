import { destination } from '@posthog/sdk/define'

import { button, cut, errorTrackingIssueUrl, escaped, hog, postToSlack, slackTemplate, verbatim } from '../shared/slack'
import { billing } from '../shared/teams'

// Each mention carries its own trailing space, so no mentions leave no stray space.
const mentions = billing.alertMentionSlackUserIds.map((id) => `<@${id}> `).join('')
const message = cut(escaped('event.properties.$exception_values[1]'), 2700)

// Billing sets these on each alert when it knows them. Each part appears only when it has a value.
const detailParts = [
    'Kind: {event.properties.alert_kind}',
    "{notEmpty(event.properties.reason) ? f' | Reason: {event.properties.reason}' : ''}",
    "{notEmpty(event.properties.mismatch) ? f' | Mismatch: {event.properties.mismatch}' : ''}",
    "{event.properties.payer_id != null ? f' | Payer: {event.properties.payer_id}' : ''}",
    "{event.properties.payer_id == null and notEmpty(event.properties.payer_ids) ? concat(' | Payers: ', arrayStringConcat(event.properties.payer_ids, ', ')) : ''}",
    "{notEmpty(event.properties.organization_id) ? f' | Organization: {event.properties.organization_id}' : ''}",
    "{event.properties.customer_count != null ? f' | Customers: {event.properties.customer_count}' : ''}",
    "{notEmpty(event.properties.oldest_link_started_at) ? f' | Waiting since: {event.properties.oldest_link_started_at}' : ''}",
    "{(event.properties.with_stripe_customer_count ?? 0) > 0 ? f' | With Stripe customer: {event.properties.with_stripe_customer_count}' : ''}",
    "{notEmpty(event.properties.organization_ids) ? concat(' | Organizations: ', substring(arrayStringConcat(event.properties.organization_ids, ', '), 1, 2500)) : ''}",
]
const details = cut(escaped(`f'${detailParts.join('')}'`), 3000)

// Posts every partner billing $exception, which billing reports with capture_message or
// capture_exception and marks with partner_billing_alert and alert_kind.
export const partnerBillingAlert = destination('partner_billing_alert', {
    name: 'Partner billing alert to Slack',
    description: 'Post to Slack on every $exception with partner_billing_alert = true',
    type: 'destination',
    enabled: true,
    hog: postToSlack,
    inputs: {
        // Slack shows this text in notifications, where verbatim can't be set, so it holds no event values.
        text: hog(`${mentions}Partner billing alert`),
        blocks: hog([
            { text: verbatim(`${mentions}{${message}}`), type: 'section' },
            { type: 'context', elements: [verbatim(`{${details}}`)] },
            { type: 'actions', elements: [button(errorTrackingIssueUrl, 'View issue')] },
        ]),
        channel: hog(billing.slackChannelId),
        username: hog('Partner billing'),
        icon_emoji: hog(':hogzilla:'),
        slack_workspace: hog(billing.slackWorkspaceId),
    },
    filters: {
        source: 'events',
        events: [{ id: '$exception', type: 'events' }],
        properties: [{ key: 'partner_billing_alert', type: 'event', value: ['true'], operator: 'exact' }],
    },
    ...slackTemplate,
})
