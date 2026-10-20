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

const { defaultSlackClient } = require('./ci-alerts-devex')

const EVENT_TYPE = 'image_build_cancellations'
const HISTORY_LIMIT = 100
const ACTIVE_COLOR = '#E01E5A'
const RESOLVED_COLOR = '#2EB67D'

// cancelledRuns holds each workflow's cancelled master push runs in the window, newest first.
function findCancellingWorkflows(cancelledRuns, threshold) {
    return cancelledRuns
        .filter(({ runs }) => runs.length >= threshold)
        .map(({ workflowFile, runs }) => ({
            workflowFile,
            name: runs[0].name,
            count: runs.length,
            newestRunUrl: runs[0].html_url,
        }))
}

async function findActiveAlert(slack, channel) {
    const { messages = [] } = await slack.history({ channel, limit: HISTORY_LIMIT })
    const anchor = messages.find(
        (message) => message.metadata?.event_type === EVENT_TYPE && message.metadata.event_payload?.status === 'active'
    )
    return anchor ? { ts: anchor.ts } : null
}

function buildActiveMessage(cancelling, { owner, repo, lookbackMinutes }) {
    const lines = cancelling.map(
        (wf) =>
            `• *<https://github.com/${owner}/${repo}/actions/workflows/${wf.workflowFile}?query=branch%3Amaster|${wf.name}>*: ` +
            `${wf.count} cancelled master runs in the last ${lookbackMinutes} minutes, <${wf.newestRunUrl}|newest run>`
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
        text: `Image builds are being cancelled on master: ${cancelling.map((wf) => wf.name).join(', ')}`,
        attachments: [{ color: ACTIVE_COLOR, blocks }],
    }
}

function buildResolvedMessage() {
    const text = ':white_check_mark: Image builds on master are no longer being cancelled'
    return { text, attachments: [{ color: RESOLVED_COLOR, blocks: [{ type: 'section', text: { type: 'mrkdwn', text } }] }] }
}

module.exports = async ({ context, github }, { now: _now, slack: _slack } = {}) => {
    const now = _now || new Date()
    const { owner, repo } = context.repo
    const channel = process.env.SLACK_CHANNEL
    const slack = _slack || defaultSlackClient(process.env.SLACK_BOT_TOKEN)
    const lookbackMinutes = parseInt(process.env.CANCELLED_BUILD_LOOKBACK_MINUTES || '120', 10)
    const threshold = parseInt(process.env.CANCELLED_BUILD_THRESHOLD || '3', 10)
    const workflowFiles = (process.env.IMAGE_BUILD_WORKFLOWS || '')
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean)

    const created = `>=${new Date(now.getTime() - lookbackMinutes * 60000).toISOString()}`
    const cancelledRuns = await Promise.all(
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
    )
    const cancelling = findCancellingWorkflows(cancelledRuns, threshold)
    const active = await findActiveAlert(slack, channel)

    if (cancelling.length > 0) {
        const message = buildActiveMessage(cancelling, { owner, repo, lookbackMinutes })
        const metadata = { event_type: EVENT_TYPE, event_payload: { status: 'active' } }
        if (active) {
            await slack.update({ channel, ts: active.ts, ...message, metadata })
        } else {
            await slack.postMessage({ channel, ...message, metadata, unfurl_links: false })
        }
    } else if (active) {
        const metadata = { event_type: EVENT_TYPE, event_payload: { status: 'resolved' } }
        await slack.update({ channel, ts: active.ts, ...buildResolvedMessage(), metadata })
    }
}

module.exports.findCancellingWorkflows = findCancellingWorkflows
