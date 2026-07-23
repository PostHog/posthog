// Auto-reruns a Frontend CI run's failed jobs when the ONLY thing that failed
// was a runner shutdown — a spot-instance preemption or the runner service
// being recycled mid-step. GitHub surfaces this as "The operation was canceled"
// / "The runner has received a shutdown signal", not a real command failure.
// A plain re-run passes on the same commit, so we absorb the flake automatically
// instead of pinging a human to click "re-run".
//
// Safety: we only rerun when at least one leaf job failed with the transient
// signature AND no leaf job failed for any other reason — so a genuine test or
// type error is never masked. Aggregator gate jobs (e.g. "Frontend Tests Pass")
// only mirror their dependencies, so they're excluded from the decision.
// A per-run attempt cap stops an infinite rerun loop if the flake is persistent.

// Failure-annotation text that marks an externally-killed runner (not a real failure).
const TRANSIENT_PATTERNS = [/operation was canceled/i, /runner has received a shutdown signal/i]

// Aggregator jobs whose failure only reflects a failed dependency — ignored when
// deciding whether the underlying failure was transient.
const GATE_JOB_PATTERN = /Tests Pass$/

// Stop retrying once a run has reached this many attempts (so we auto-rerun at most twice).
const DEFAULT_MAX_ATTEMPTS = 3

// A job failed transiently when it emitted failure annotations and every one of
// them matches the runner-shutdown signature (no other failure reason present).
function isTransientFailure(failureMessages) {
    return failureMessages.length > 0 && failureMessages.every((m) => TRANSIENT_PATTERNS.some((p) => p.test(m)))
}

// Pure decision used by the orchestrator and the tests. `jobs` is the run's jobs
// shaped as { name, conclusion, failureMessages: string[] }.
function shouldRerun({ conclusion, runAttempt, maxAttempts = DEFAULT_MAX_ATTEMPTS, jobs }) {
    if (conclusion !== 'failure') {
        return false
    }
    if (runAttempt >= maxAttempts) {
        return false
    }

    const failedLeafJobs = jobs.filter(
        (j) => (j.conclusion === 'failure' || j.conclusion === 'cancelled') && !GATE_JOB_PATTERN.test(j.name)
    )
    if (failedLeafJobs.length === 0) {
        return false
    }

    // Any non-transient leaf failure means a real problem — don't mask it.
    return failedLeafJobs.every((j) => isTransientFailure(j.failureMessages))
}

module.exports = async ({ github, context, core }) => {
    const run = context.payload.workflow_run
    const { owner, repo } = context.repo
    const maxAttempts = Number(process.env.MAX_ATTEMPTS || DEFAULT_MAX_ATTEMPTS)

    if (run.conclusion !== 'failure') {
        core.info(`Run ${run.id} concluded '${run.conclusion}', not 'failure' — nothing to do.`)
        return
    }
    if (run.run_attempt >= maxAttempts) {
        core.info(`Run ${run.id} is on attempt ${run.run_attempt} (cap ${maxAttempts}) — not retrying again.`)
        return
    }

    const rawJobs = await github.paginate(github.rest.actions.listJobsForWorkflowRunAttempt, {
        owner,
        repo,
        run_id: run.id,
        attempt_number: run.run_attempt,
        per_page: 100,
    })

    const jobs = []
    for (const job of rawJobs) {
        if (job.conclusion !== 'failure' && job.conclusion !== 'cancelled') {
            continue
        }
        const annotations = await github.paginate(github.rest.checks.listAnnotations, {
            owner,
            repo,
            check_run_id: job.id,
            per_page: 100,
        })
        jobs.push({
            name: job.name,
            conclusion: job.conclusion,
            failureMessages: annotations.filter((a) => a.annotation_level === 'failure').map((a) => a.message),
        })
    }

    if (!shouldRerun({ conclusion: run.conclusion, runAttempt: run.run_attempt, maxAttempts, jobs })) {
        core.info(`Run ${run.id}: failure was not purely a transient runner shutdown — leaving it alone.`)
        return
    }

    core.info(`Re-running failed jobs of run ${run.id} (attempt ${run.run_attempt}) after transient runner shutdown.`)
    await github.rest.actions.reRunWorkflowFailedJobs({ owner, repo, run_id: run.id })
}

module.exports.shouldRerun = shouldRerun
module.exports.isTransientFailure = isTransientFailure
