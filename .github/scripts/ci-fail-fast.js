// CI Fail-Fast — when a required CI workflow fails on a PR, cancel the sibling CI
// runs still in flight for the same commit. A tainted run is rarely salvaged by
// re-running just the failed check; the usual next step is a new push, which
// re-runs everything anyway, so finishing the rest burns runner minutes for a
// result nobody reads.
//
// Driven by two environment inputs (set from `vars` / workflow env in the YAML):
//   CI_FAIL_FAST_MODE      "off" (default) | "dry" | "on"
//   CI_FAIL_FAST_ALLOWLIST JSON array of workflow names that may be cancelled
//
// "dry" logs what it WOULD cancel and cancels nothing — the safe rollout default
// that doubles as the data source for the pristine-vs-tainted experiment (grep
// run logs for the FAIL_FAST_DATA line).

const ACTIVE_STATUSES = new Set(['queued', 'in_progress', 'requested', 'waiting', 'pending'])

// Pure: of the runs sharing a commit, pick the ones safe to cancel.
function selectCancellableRuns({ runs, sourceRunId, allow }) {
    return runs.filter((r) => {
        if (r.id === sourceRunId) return false // never the run that triggered us
        if (!ACTIVE_STATUSES.has(r.status)) return false // already finished
        if (r.event !== 'pull_request') return false // never a push/master run sharing the SHA
        return allow.has(r.name) // allowlist only — never deploys or container builds
    })
}

function parseAllowlist(raw) {
    if (!raw) return new Set()
    return new Set(
        JSON.parse(raw)
            .map((s) => String(s).trim())
            .filter(Boolean)
    )
}

const shortSha = (sha) => (sha || '').slice(0, 7)

module.exports = async ({ github, context, core }) => {
    const mode = (process.env.CI_FAIL_FAST_MODE || 'off').trim()
    const allow = parseAllowlist(process.env.CI_FAIL_FAST_ALLOWLIST)
    const source = context.payload.workflow_run
    const headSha = source.head_sha
    const prNumber = source.pull_requests?.[0]?.number ?? null
    const live = mode === 'on'
    const label = live
        ? { gerund: 'Cancelling', past: 'Cancelled' }
        : { gerund: '[dry-run] Would cancel', past: 'Would cancel' }

    const runs = await github.paginate(github.rest.actions.listWorkflowRunsForRepo, {
        owner: context.repo.owner,
        repo: context.repo.repo,
        head_sha: headSha,
        event: 'pull_request', // narrow server-side; selectCancellableRuns re-checks defensively
        per_page: 100,
    })
    const cancellable = selectCancellableRuns({ runs, sourceRunId: source.id, allow })

    // Structured record for the pristine-vs-tainted experiment, greppable via the
    // Actions API. Captures the half you cannot reconstruct later: how much was
    // still in flight at the moment of failure.
    console.log(
        `FAIL_FAST_DATA ${JSON.stringify({
            mode,
            sha: headSha,
            pr: prNumber,
            trigger: { workflow: source.name, run_id: source.id, conclusion: source.conclusion },
            cancellable: cancellable.map((r) => ({ workflow: r.name, run_id: r.id, status: r.status })),
            count: cancellable.length,
        })}`
    )

    if (cancellable.length === 0) {
        core.notice(`No sibling CI runs in flight for ${shortSha(headSha)} (triggered by ${source.name} failure)`)
    }
    for (const r of cancellable) {
        core.notice(`${label.gerund}: ${r.name} #${r.id} (${r.status})`)
        if (live) {
            await github.rest.actions
                .cancelWorkflowRun({ owner: context.repo.owner, repo: context.repo.repo, run_id: r.id })
                // A near-simultaneous failure can cancel the same run first; that 409 is expected.
                .catch((e) => core.warning(`Could not cancel ${r.name} #${r.id}: ${e.message}`))
        }
    }

    const prNote = prNumber ? ` (PR #${prNumber})` : ''
    const headline = cancellable.length
        ? `${label.past} ${cancellable.length} sibling CI run(s) on ${shortSha(headSha)}${prNote} after ${source.name} failed`
        : ''

    const table = cancellable.map((r) => `| ${r.name} | ${r.status} |`).join('\n')
    await core.summary
        .addHeading(`CI Fail-Fast — ${mode.toUpperCase()}`)
        .addRaw(`Triggered by **${source.name}** failing on \`${shortSha(headSha)}\`${prNote}.\n\n`)
        .addRaw(headline ? `${headline}:\n\n| Workflow | Status |\n| --- | --- |\n${table}\n` : 'No sibling CI runs were in flight.\n')
        .write()

    core.setOutput('mode', mode)
    core.setOutput('count', String(cancellable.length))
    core.setOutput('summary', headline ? `${headline}: ${cancellable.map((r) => r.name).join(', ')}` : '')
}

module.exports.selectCancellableRuns = selectCancellableRuns
module.exports.parseAllowlist = parseAllowlist
