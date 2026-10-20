// Image build cancellations: one self-updating Slack alert for image workflows whose master runs
// keep getting cancelled.
//
// A cancelled master run of an image workflow never builds the changes in its push, and no later
// run builds them unless its own push touches the same paths. Those workflows key their push
// concurrency per SHA, so a master run is only cancelled by hand or by a regression in that key.
// A run of cancellations means changes are reaching master and not deploying.
//
// Detection is stateless like ci-alerts-devex.js: every tick counts cancelled master push runs in
// a rolling window, and the bot's own anchor message (found by its Slack metadata) carries the
// open/resolved state.

const { defaultSlackClient, findActiveIncident } = require('./ci-alerts-devex')

const EVENT_TYPE = 'image_build_cancellations'
const ACTIVE_COLOR = '#E01E5A'
const RESOLVED_COLOR = '#2EB67D'

// Each entry holds one workflow's cancelled master push runs in the window, newest first.
function buildActiveMessage(cancelling, { owner, repo, lookbackMinutes }) {
    const lines = cancelling.map(
        ({ workflowFile, runs }) =>
            `• *<https://github.com/${owner}/${repo}/actions/workflows/${workflowFile}?query=branch%3Amaster|${runs[0].name}>*: ` +
            `${runs.length} cancelled master runs in the last ${lookbackMinutes} minutes, <${runs[0].html_url}|newest run>`
    )
    const blocks = [
        { type: 'header', text: { type: 'plain_text', text: ':warning: Image builds are being cancelled on master' } },
        { type: 'section', text: { type: 'mrkdwn', text: lines.join('\n') } },
        {
            type: 'context',
            elements: [
                {
                    type: 'mrkdwn',
                    text: "A cancelled run never builds the changes in its push. Check the workflow's concurrency group and deploy any change it dropped.",
                },
            ],
        },
    ]
    return {
        text: `Image builds are being cancelled on master: ${cancelling.map(({ runs }) => runs[0].name).join(', ')}`,
        attachments: [{ color: ACTIVE_COLOR, blocks }],
    }
}

function buildResolvedMessage() {
    const text = ':white_check_mark: Image builds on master are no longer being cancelled'
    return {
        text,
        attachments: [{ color: RESOLVED_COLOR, blocks: [{ type: 'section', text: { type: 'mrkdwn', text } }] }],
    }
}

module.exports = async ({ context, github }, { slack: _slack } = {}) => {
    const { owner, repo } = context.repo
    const channel = process.env.SLACK_CHANNEL
    const slack = _slack || defaultSlackClient(process.env.SLACK_BOT_TOKEN)
    const lookbackMinutes = parseInt(process.env.CANCELLED_BUILD_LOOKBACK_MINUTES, 10)
    const threshold = parseInt(process.env.CANCELLED_BUILD_THRESHOLD, 10)
    const workflowFiles = process.env.IMAGE_BUILD_WORKFLOWS.split(',').map((entry) => entry.trim())

    const created = `>=${new Date(Date.now() - lookbackMinutes * 60000).toISOString()}`
    const [cancelledRuns, active] = await Promise.all([
        Promise.all(
            workflowFiles.map(async (workflowFile) => {
                const { data } = await github.rest.actions.listWorkflowRuns({
                    owner,
                    repo,
                    workflow_id: workflowFile,
                    branch: 'master',
                    event: 'push',
                    status: 'cancelled',
                    created,
                    per_page: 100,
                })
                return { workflowFile, runs: data.workflow_runs }
            })
        ),
        findActiveIncident(slack, channel, EVENT_TYPE),
    ])
    const cancelling = cancelledRuns.filter(({ runs }) => runs.length >= threshold)
    if (cancelling.length === 0 && !active) {
        return
    }

    const status = cancelling.length > 0 ? 'active' : 'resolved'
    const message =
        status === 'active' ? buildActiveMessage(cancelling, { owner, repo, lookbackMinutes }) : buildResolvedMessage()
    const metadata = { event_type: EVENT_TYPE, event_payload: { status } }
    if (active) {
        await slack.update({ channel, ts: active.ts, ...message, metadata })
    } else {
        await slack.postMessage({ channel, ...message, metadata, unfurl_links: false })
    }
}
