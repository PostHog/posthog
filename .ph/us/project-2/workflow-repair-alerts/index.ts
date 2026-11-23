import { destination } from '@posthog/sdk/define'

import { button, hog, plainText, slackTemplate } from '../shared/slack'
import { billing } from '../shared/teams'

const postRepairNotice = `let res := fetch('https://slack.com/api/chat.postMessage', {
  'method': 'POST',
  'headers': {'Authorization': f'Bearer {inputs.slack_workspace.access_token}', 'Content-Type': 'application/json'},
  'body': {'channel': inputs.channel, 'blocks': inputs.blocks, 'text': inputs.text}
});
if (res.status != 200 or res.body.ok == false) {
  throw Error(f'Failed to post repair notification: {res.status}: {res.body}');
}
`

// Project 2 accepts public events, so their properties go in as plain text, and the link is built
// from encoded path parts on the Temporal Cloud host.
const encoded = (property: string): string => `{encodeURLComponent(toString(event.properties.${property}))}`
const workflowUrl = `https://cloud.temporal.io/namespaces/${encoded('namespace')}/workflows/${encoded('workflow_id')}/${encoded('run_id')}/history`

const report = [
    'Billing repair #{event.properties.repair_id}',
    "Attempt: {event.properties.attempt ?? 'Unknown'}",
    "Billing customer: {event.properties.customer_id ?? 'Unknown'}",
    'Machine: {event.properties.machine}',
    'Workflow ID: {event.properties.workflow_id}',
    "Workflow key: {event.properties.workflow_key ?? 'Unknown'}",
    "Source fact: {event.properties.source_fact_id} ({event.properties.source_fact_type ?? 'Unknown'})",
    'Reason: {event.properties.reason}',
].join('\n')

export const spineRepairRequired = destination('spine_repair_required', {
    name: 'billing workflow repair alerts',
    description: 'Notify billing when a workflow saves a repair report and waits for an operator.',
    type: 'destination',
    enabled: true,
    ...slackTemplate,
    hog: postRepairNotice,
    inputs: {
        text: hog('A billing workflow needs repair'),
        channel: hog(billing.slackChannelId),
        slack_workspace: hog(billing.slackWorkspaceId),
        blocks: hog([
            { type: 'section', text: plainText(`{substring(f'${report}', 1, 3000)}`) },
            { type: 'actions', elements: [button(workflowUrl, 'View workflow')] },
        ]),
    },
    filters: {
        source: 'events',
        events: [{ id: 'billing spine repair required', type: 'events' }],
        properties: [
            { key: 'repo_identifier', type: 'event', value: ['billing'], operator: 'exact' },
            { key: 'billing_site_url', type: 'event', value: ['https://billing.posthog.com'], operator: 'exact' },
        ],
    },
})
