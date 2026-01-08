// Master CI Status - Latching alarm model for tracking CI failures on master
//
// State structure:
// {
//   channel: string,      // Slack channel ID
//   ts: string,           // Slack message timestamp (thread parent)
//   since: string,        // ISO timestamp of incident start
//   sha_ts: {[sha]: number},        // sha -> commit timestamp (epoch ms)
//   fail_ts: {[workflow]: number},  // workflow -> timestamp of last failure
//   ok_ts: {[workflow]: number}     // workflow -> timestamp of last success
// }
//
// A workflow is "known failing" iff fail_ts[w] > ok_ts[w]
// Resolution occurs when no workflows are known failing

const STATE_FILE = '.master-ci-incident';

async function getCommitTimestamp(github, context, sha) {
    const { data } = await github.rest.repos.getCommit({
        owner: context.repo.owner,
        repo: context.repo.repo,
        ref: sha,
    });
    const iso = data.commit.committer?.date ?? data.commit.author?.date;
    return new Date(iso).getTime();
}

function getFailingWorkflows(state) {
    return Object.entries(state.fail_ts)
        .filter(([wf, ts]) => ts > (state.ok_ts[wf] ?? 0))
        .map(([wf]) => wf);
}

function pruneOldShas(state) {
    // Remove sha_ts entries older than the minimum ok_ts.
    // Once all workflows have passed on a commit newer than a SHA,
    // that SHA's timestamp is no longer needed for ordering comparisons.
    const okTimestamps = Object.values(state.ok_ts);
    if (okTimestamps.length === 0) return;

    const minOkTs = Math.min(...okTimestamps);
    for (const sha of Object.keys(state.sha_ts)) {
        if (state.sha_ts[sha] < minOkTs) {
            delete state.sha_ts[sha];
        }
    }
}

function handleFailure(state, event, commitTs, core, fs) {
    const isNew = !state;

    if (isNew) {
        state = {
            // Use the failing commit's timestamp as incident start, not wall clock.
            // This ensures pendingWorkflows check compares against when the failure
            // was authored, not when we detected it (which could be much later).
            since: new Date(commitTs).toISOString(),
            sha_ts: { [event.head_sha]: commitTs },
            fail_ts: { [event.name]: commitTs },
            ok_ts: {},
        };
    } else {
        // Record this SHA's timestamp
        state.sha_ts[event.head_sha] = commitTs;
        // Update fail_ts: max of current and new timestamp
        state.fail_ts[event.name] = Math.max(state.fail_ts[event.name] ?? 0, commitTs);
    }

    const failing = getFailingWorkflows(state);
    pruneOldShas(state);
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));

    core.setOutput('action', isNew ? 'create' : 'update');
    core.setOutput('failing_workflows', failing.join(', '));
    core.setOutput('failing_count', String(failing.length));
    core.setOutput('commit_count', String(Object.keys(state.sha_ts).length));
    core.setOutput('save_cache', 'true');

    console.log(`Action: ${isNew ? 'create' : 'update'}`);
    console.log(`Failing workflows: ${failing.join(', ')}`);
    console.log(`State:`, JSON.stringify(state, null, 2));
}

function handleSuccess(state, event, commitTs, core, fs) {
    if (!state) {
        core.setOutput('action', 'none');
        core.setOutput('save_cache', 'false');
        console.log('No incident exists, nothing to do');
        return;
    }

    // Check if this workflow was failing before this success
    const wasFailing =
        (state.fail_ts[event.name] ?? 0) > (state.ok_ts[event.name] ?? 0) && commitTs > (state.fail_ts[event.name] ?? 0);

    // Record this SHA's timestamp
    state.sha_ts[event.head_sha] = commitTs;
    // Update ok_ts: max of current and new timestamp
    state.ok_ts[event.name] = Math.max(state.ok_ts[event.name] ?? 0, commitTs);

    const failing = getFailingWorkflows(state);

    // Check all required workflows have passed since incident start
    const requiredWorkflows = (process.env.REQUIRED_WORKFLOWS || '').split(',').filter(Boolean);
    const incidentStart = new Date(state.since).getTime();
    const pendingWorkflows = requiredWorkflows.filter((wf) => (state.ok_ts[wf] ?? 0) < incidentStart);
    const resolved = failing.length === 0 && pendingWorkflows.length === 0;

    if (resolved) {
        state.resolved = true;
    }

    pruneOldShas(state);
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));

    core.setOutput('action', wasFailing ? 'resolve' : 'none');
    core.setOutput('recovered_workflow', wasFailing ? event.name : '');
    core.setOutput('still_failing', failing.join(', '));
    core.setOutput('commit_count', String(Object.keys(state.sha_ts).length));
    core.setOutput('resolved', resolved ? 'true' : 'false');
    core.setOutput('since', state.since);
    core.setOutput('channel', state.channel || '');
    core.setOutput('ts', state.ts || '');
    core.setOutput('save_cache', 'true');

    console.log(`Action: ${wasFailing ? 'resolve' : 'none'}`);
    console.log(`Recovered: ${wasFailing ? event.name : 'none'}`);
    console.log(`Still failing: ${failing.join(', ') || 'none'}`);
    console.log(`Pending (not passed since incident): ${pendingWorkflows.join(', ') || 'none'}`);
    console.log(`State:`, JSON.stringify(state, null, 2));
}

module.exports = async ({ github, context, core }) => {
    const fs = require('fs');
    const event = context.payload.workflow_run;
    const conclusion = event.conclusion;

    console.log(`Processing ${event.name} (${conclusion}) for ${event.head_sha.substring(0, 7)}`);

    // Read existing state
    let state = null;
    if (fs.existsSync(STATE_FILE)) {
        try {
            const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
            // If incident was already resolved, treat as no incident
            if (raw.resolved) {
                console.log('Found resolved incident, treating as no active incident');
            } else {
                // Ensure required fields exist (handles old format or corrupted state)
                state = {
                    ...raw,
                    sha_ts: raw.sha_ts || {},
                    fail_ts: raw.fail_ts || {},
                    ok_ts: raw.ok_ts || {},
                };
                console.log('Loaded existing incident state');
            }
        } catch (e) {
            console.log('Failed to parse state file, treating as no incident');
        }
    }

    // Get commit timestamp from GitHub API
    const commitTs = await getCommitTimestamp(github, context, event.head_sha);
    console.log(`Commit timestamp: ${new Date(commitTs).toISOString()}`);

    // Handle based on conclusion
    if (conclusion === 'failure' || conclusion === 'timed_out') {
        handleFailure(state, event, commitTs, core, fs);
    } else if (conclusion === 'success') {
        handleSuccess(state, event, commitTs, core, fs);
    } else {
        // Ignore cancelled, skipped, etc. - no state change
        core.setOutput('action', 'none');
        core.setOutput('save_cache', 'false');
        console.log(`Ignoring ${conclusion} conclusion`);
    }
};
