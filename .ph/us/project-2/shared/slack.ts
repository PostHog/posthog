// The Slack destination template's code, as PostHog's Slack template writes it.
export const postToSlack = `let res := fetch('https://slack.com/api/chat.postMessage', {
  'body': {
    'channel': inputs.channel,
    'icon_emoji': inputs.icon_emoji,
    'username': inputs.username,
    'blocks': inputs.blocks,
    'text': inputs.text
  },
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status != 200 or res.body.ok == false) {
  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');
}`

export const slackTemplate = { template_id: 'template-slack', icon_url: '/static/services/slack.png' }

// A destination input whose value is a hog template.
export const hog = <T>(value: T): { value: T; templating: 'hog' } => ({ value, templating: 'hog' })

export type PlainText = { text: string; type: 'plain_text' }
export const plainText = (text: string): PlainText => ({ text, type: 'plain_text' })

export type Mrkdwn = { text: string; type: 'mrkdwn'; verbatim: true }
// Slack renders verbatim text without turning it into links or mentions.
export const verbatim = (text: string): Mrkdwn => ({ text, type: 'mrkdwn', verbatim: true })

export const button = (url: string, label: string): { url: string; text: PlainText; type: 'button' } => ({
    url,
    text: plainText(label),
    type: 'button',
})

// The blocks of an alert's "firing" message, with links to the insight and the alert.
export const alertFiringBlocks = [
    {
        text: plainText("Alert '{event.properties.alert_name}' firing for insight '{event.properties.insight_name}'"),
        type: 'header',
    },
    { text: plainText('{event.properties.breaches}'), type: 'section' },
    { type: 'context', elements: [{ text: 'Project: <{project.url}|{project.name}>', type: 'mrkdwn' }] },
    { type: 'divider' },
    {
        type: 'actions',
        elements: [
            button('{project.url}/insights/{event.properties.insight_id}', 'View Insight'),
            button(
                '{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}',
                'View Alert'
            ),
        ],
    },
]

// Anyone with project 2's public key can send an event that passes a destination's filter, so every
// event value in a Slack message is escaped before it can add links or mentions.
export function escaped(expression: string): string {
    return `replaceAll(replaceAll(replaceAll(toString(${expression} ?? ''), '&', '&amp;'), '<', '&lt;'), '>', '&gt;')`
}

// Slack rejects a section over 3,000 characters.
export function cut(expression: string, length: number): string {
    return `substring(${expression}, 1, ${length})`
}

export const errorTrackingIssueUrl =
    "{project.url}/error_tracking/{encodeURLComponent(toString(event.properties.$exception_issue_id ?? ''))}"
