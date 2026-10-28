const COST_PR_BRANCH = 'chore/llma-update-ai-costs'
const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS
const REPLACEMENT_WINDOW_MS = 30 * 60 * 1000
const EARLY_ALERT_HOURS = [2, 8]
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

function findApprovedAt(reviewDecision, latestReviews) {
    if (reviewDecision !== 'APPROVED') {
        return null
    }
    const approvals = latestReviews
        .filter((review) => review.state === 'APPROVED')
        .map((review) => Date.parse(review.submittedAt))
    return approvals.length > 0 ? Math.min(...approvals) : null
}

function isAlertDue({ stuckSince, lastCheckAt, thisCheckAt }) {
    const nextDailyAlert = stuckSince + Math.max(1, Math.floor((lastCheckAt - stuckSince) / DAY_MS) + 1) * DAY_MS
    const alertTimes = [...EARLY_ALERT_HOURS.map((hours) => stuckSince + hours * HOUR_MS), nextDailyAlert]
    return alertTimes.some((time) => time > lastCheckAt && time <= thisCheckAt)
}

function buildAlertText({ pr, waitingSince, prCount, approvedAt, now, supportHeroGroup, aiObservabilityGroup }) {
    const hoursSince = (time) => Math.floor((now - time) / HOUR_MS)
    const waitedHours = hoursSince(waitingSince)
    const groups =
        waitedHours >= AI_OBSERVABILITY_AFTER_HOURS ? [supportHeroGroup, aiObservabilityGroup] : [supportHeroGroup]
    const mentions = groups.map((group) => `<!subteam^${group}>`).join(' ')
    const problem = approvedAt
        ? `was approved ${hoursSince(approvedAt)}h ago but has not merged. Check if the merge queue kicked it out.`
        : 'needs a review.'
    const history = prCount > 1 ? ` across ${prCount} PRs` : ''
    return `${mentions} LLM cost update <${pr.html_url}|#${pr.number}> ${problem} New prices have waited ${waitedHours}h${history}.`
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

async function fetchReviewState({ github, owner, repo, number }) {
    const { repository } = await github.graphql(
        `query ($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                pullRequest(number: $number) {
                    reviewDecision
                    latestReviews(first: 20) {
                        nodes {
                            state
                            submittedAt
                        }
                    }
                }
            }
        }`,
        { owner, repo, number }
    )
    const { reviewDecision, latestReviews } = repository.pullRequest
    return { reviewDecision, latestReviews: latestReviews.nodes }
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
    const { reviewDecision, latestReviews } = await fetchReviewState({ github, owner, repo, number: pr.number })
    const approvedAt = findApprovedAt(reviewDecision, latestReviews)

    if (!isAlertDue({ stuckSince: approvedAt ?? waitingSince, lastCheckAt, thisCheckAt })) {
        core.info(`#${pr.number} is ${reviewDecision}: no alert due`)
        return
    }

    const text = buildAlertText({
        pr,
        waitingSince,
        prCount,
        approvedAt,
        now: Date.now(),
        supportHeroGroup,
        aiObservabilityGroup,
    })
    core.info(text)
    core.setOutput('text', text)
}

module.exports = checkStaleCostPr
module.exports.findWaitingSince = findWaitingSince
module.exports.findApprovedAt = findApprovedAt
module.exports.isAlertDue = isAlertDue
module.exports.buildAlertText = buildAlertText
