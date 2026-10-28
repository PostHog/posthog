// Pings #support-agent-infra until the automated LLM cost PR merges. Runs hourly on weekdays.
//
// Pings when the PR is posted, again at 8h, then every 24h.
// The clock starts at the first unmerged PR, since each cost refresh replaces the open one.
// The support hero is always tagged. AI observability joins once new prices have waited 24h.
// Each run covers the time since the last successful run, so a missed run catches up on the next.

const COST_PR_BRANCH = 'chore/llma-update-ai-costs'
const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS
const REPLACEMENT_WINDOW_MS = 30 * 60 * 1000
const EARLY_ALERT_HOURS = [0, 8]
const AI_OBSERVABILITY_AFTER_HOURS = 24

function findWaitingSince(prs) {
    const [current, ...older] = prs
    let waitingSince = Date.parse(current.created_at)
    let prCount = 1
    for (const pr of older) {
        const replacedImmediately = Math.abs(waitingSince - Date.parse(pr.closed_at)) < REPLACEMENT_WINDOW_MS
        if (pr.merged_at || !replacedImmediately) {
            break
        }
        waitingSince = Date.parse(pr.created_at)
        prCount++
    }
    return { waitingSince, prCount }
}

function isAlertDue({ waitingSince, lastCheckAt, thisCheckAt }) {
    const nextDailyAlert = waitingSince + Math.max(1, Math.floor((lastCheckAt - waitingSince) / DAY_MS) + 1) * DAY_MS
    const alertTimes = [...EARLY_ALERT_HOURS.map((hours) => waitingSince + hours * HOUR_MS), nextDailyAlert]
    return alertTimes.some((time) => time > lastCheckAt && time <= thisCheckAt)
}

function buildAlertText({ pr, waitingSince, prCount, now, supportHeroGroup, aiObservabilityGroup }) {
    const waitedHours = Math.floor((now - waitingSince) / HOUR_MS)
    const groups =
        waitedHours >= AI_OBSERVABILITY_AFTER_HOURS ? [supportHeroGroup, aiObservabilityGroup] : [supportHeroGroup]
    const mentions = groups.map((group) => `<!subteam^${group}>`).join(' ')
    const link = `<${pr.html_url}|#${pr.number}>`
    if (waitedHours === 0) {
        return `${mentions} New LLM cost update ${link} needs to merge.`
    }
    const history = prCount > 1 ? ` across ${prCount} PRs` : ''
    return `${mentions} LLM cost update ${link} has not merged. New prices have waited ${waitedHours}h${history}.`
}

async function findCheckWindow({ github, owner, repo, runId }) {
    const { data: thisRun } = await github.rest.actions.getWorkflowRun({ owner, repo, run_id: runId })
    const thisCheckAt = Date.parse(thisRun.created_at)
    const { data: successfulRuns } = await github.rest.actions.listWorkflowRuns({
        owner,
        repo,
        workflow_id: thisRun.workflow_id,
        status: 'success',
        per_page: 10,
    })
    const lastSuccess = successfulRuns.workflow_runs.find(
        (run) => run.id !== thisRun.id && Date.parse(run.created_at) < thisCheckAt
    )
    const lastCheckAt = lastSuccess ? Date.parse(lastSuccess.created_at) : thisCheckAt - HOUR_MS
    return { lastCheckAt, thisCheckAt }
}

async function listCostPrsSinceLastMerge({ github, owner, repo }) {
    return github.paginate(
        github.rest.pulls.list,
        {
            owner,
            repo,
            head: `${owner}:${COST_PR_BRANCH}`,
            state: 'all',
            sort: 'created',
            direction: 'desc',
            per_page: 100,
        },
        (response, done) => {
            if (response.data.some((pr) => pr.merged_at)) {
                done()
            }
            return response.data
        }
    )
}

async function checkStaleCostPr({ github, context, core }, { supportHeroGroup, aiObservabilityGroup }) {
    const { owner, repo } = context.repo
    const { lastCheckAt, thisCheckAt } = await findCheckWindow({ github, owner, repo, runId: context.runId })

    const prs = await listCostPrsSinceLastMerge({ github, owner, repo })
    const pr = prs[0]
    if (!pr || pr.state !== 'open') {
        core.info('No open LLM cost PR')
        return
    }

    const { waitingSince, prCount } = findWaitingSince(prs)
    if (!isAlertDue({ waitingSince, lastCheckAt, thisCheckAt })) {
        core.info(`#${pr.number} is open: no alert due`)
        return
    }

    const text = buildAlertText({ pr, waitingSince, prCount, now: Date.now(), supportHeroGroup, aiObservabilityGroup })
    core.info(text)
    core.setOutput('text', text)
}

module.exports = checkStaleCostPr
module.exports.findWaitingSince = findWaitingSince
module.exports.isAlertDue = isAlertDue
module.exports.buildAlertText = buildAlertText
