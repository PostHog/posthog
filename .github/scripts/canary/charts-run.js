'use strict'

// Locate the charts-side workflow run that picked up our repository_dispatch.
// repository_dispatch payload is not exposed on workflow runs, so we match
// by event + workflow file + creation time relative to when we dispatched.
// There is a 1-3s race between dispatch and run creation, so we retry.

const CHARTS_OWNER = 'PostHog'
const CHARTS_REPO = 'charts'
const ENABLE_WORKFLOW = 'pr-canary-flags-enable.yml'
const DISABLE_WORKFLOW = 'pr-canary-flags-disable.yml'

function asTimestamp(t) {
    if (!t) return Date.now()
    if (typeof t === 'string') return new Date(t).getTime()
    if (t instanceof Date) return t.getTime()
    return t
}

async function findChartsRun({ octokit, workflowFile, dispatchedAt, retries = 15, intervalMs = 2000 }) {
    const dispatchTs = asTimestamp(dispatchedAt)
    for (let attempt = 0; attempt < retries; attempt++) {
        try {
            const { data } = await octokit.rest.actions.listWorkflowRuns({
                owner: CHARTS_OWNER,
                repo: CHARTS_REPO,
                workflow_id: workflowFile,
                event: 'repository_dispatch',
                per_page: 10,
            })
            const candidate = (data.workflow_runs || []).find((r) => {
                const created = new Date(r.created_at).getTime()
                // allow runs created up to 5s before our dispatch (clock skew) and forward
                return created >= dispatchTs - 5000
            })
            if (candidate) return candidate
        } catch (err) {
            // transient — keep retrying
        }
        if (attempt < retries - 1) {
            await new Promise((res) => setTimeout(res, intervalMs))
        }
    }
    return null
}

async function findEnableRun(opts) {
    return findChartsRun({ ...opts, workflowFile: ENABLE_WORKFLOW })
}

async function findDisableRun(opts) {
    return findChartsRun({ ...opts, workflowFile: DISABLE_WORKFLOW })
}

async function getChartsRun({ octokit, runId }) {
    const { data } = await octokit.rest.actions.getWorkflowRun({
        owner: CHARTS_OWNER,
        repo: CHARTS_REPO,
        run_id: runId,
    })
    return data
}

module.exports = {
    CHARTS_OWNER,
    CHARTS_REPO,
    ENABLE_WORKFLOW,
    DISABLE_WORKFLOW,
    asTimestamp,
    findChartsRun,
    findEnableRun,
    findDisableRun,
    getChartsRun,
}
