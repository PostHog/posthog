import { destination } from '@posthog/sdk/define'

import {
    button,
    cut,
    errorTrackingIssueUrl,
    escaped,
    hog,
    plainText,
    postToSlack,
    slackTemplate,
    verbatim,
} from '../shared/slack'
import { billing } from '../shared/teams'

const mentions = billing.alertMentionSlackUserIds.map((id) => `<@${id}>`).join(' ')
const exceptionType = cut(escaped('event.properties.$exception_types[1]'), 200)
const message = cut(escaped('event.properties.$exception_values[1]'), 2700)
const details = cut(
    escaped(
        "f'Coupon: {event.properties.coupon_id} | Credit: {event.properties.credit_id} | Customer: {event.properties.customer_id} | Organization: {event.properties.organization_id}'"
    ),
    3000
)

// Posts every $exception from a community credit claim. The billing error feed posts only new or
// reopened issues, so repeat failures of one issue would be silent there. Billing sets campaign_slug
// on the claim endpoint's exception and on "Community credit was not applied after coupon claim."
export const communityCreditClaimFailure = destination('community_credit_claim_failure', {
    name: 'Community credit claim failure to Slack',
    description: 'Post to Slack on every $exception with campaign_slug = community',
    type: 'destination',
    enabled: true,
    hog: postToSlack,
    inputs: {
        // Slack shows this text in notifications, where verbatim can't be set, so it holds no event values.
        text: hog(`${mentions} Community credit claim failed`),
        blocks: hog([
            { text: plainText('Community credit claim failed'), type: 'header' },
            { text: verbatim(`${mentions} *{${exceptionType}}*: {${message}}`), type: 'section' },
            { type: 'context', elements: [verbatim(`{${details}}`)] },
            { type: 'divider' },
            { type: 'actions', elements: [button(errorTrackingIssueUrl, 'View issue')] },
        ]),
        channel: hog(billing.slackChannelId),
        username: hog('Community credits'),
        icon_emoji: hog(':hogzilla:'),
        slack_workspace: hog(billing.slackWorkspaceId),
    },
    filters: {
        source: 'events',
        events: [{ id: '$exception', type: 'events' }],
        properties: [{ key: 'campaign_slug', type: 'event', value: ['community'], operator: 'exact' }],
    },
    ...slackTemplate,
})
