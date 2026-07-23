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
const MAX_ATTEMPTS = Number(process.env.MAX_ATTEMPTS || 3)

module.exports = async ({ github, context, core }) => {
    const run = context.payload.workflow_run
    const { owner, repo } = context.repo

    if (run.conclusion !== 'failure') {
        core.info(`Run ${run.id} concluded '${run.conclusion}', not 'failure' — nothing to do.`)
        return
    }
    if (run.run_attempt >= MAX_ATTEMPTS) {
        core.info(`Run ${run.id} is on attempt ${run.run_attempt} (cap ${MAX_ATTEMPTS}) — not retrying again.`)
        return
    }

    const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRunAttempt, {
        owner,
        repo,
        run_id: run.id,
        attempt_number: run.run_attempt,
        per_page: 100,
    })

    const failedLeafJobs = jobs.filter(
        (j) => (j.conclusion === 'failure' || j.conclusion === 'cancelled') && !GATE_JOB_PATTERN.test(j.name)
    )
    if (failedLeafJobs.length === 0) {
        core.info('No failed non-aggregator jobs — leaving the run alone (gate failed without a leaf cause).')
        return
    }

    let sawTransient = false
    for (const job of failedLeafJobs) {
        const annotations = await github.paginate(github.rest.checks.listAnnotations, {
            owner,
            repo,
            check_run_id: job.id,
            per_page: 100,
        })
        const failureMsgs = annotations.filter((a) => a.annotation_level === 'failure').map((a) => a.message)
        const isTransient =
            failureMsgs.length > 0 && failureMsgs.every((m) => TRANSIENT_PATTERNS.some((p) => p.test(m)))

        if (isTransient) {
            sawTransient = true
            core.info(`Job "${job.name}" failed transiently (runner shutdown).`)
        } else {
            core.info(`Job "${job.name}" failed for a non-transient reason — will NOT auto-rerun.`)
            return
        }
    }

    if (!sawTransient) {
        return
    }

    core.info(`Re-running failed jobs of run ${run.id} (attempt ${run.run_attempt}) after transient runner shutdown.`)
    await github.rest.actions.reRunWorkflowFailedJobs({ owner, repo, run_id: run.id })
}
