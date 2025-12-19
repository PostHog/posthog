// Master CI Status - Latching alarm model for tracking CI failures on master
//
// State structure:
// {
//   channel: string,      // Slack channel ID
//   ts: string,           // Slack message timestamp (thread parent)
//   since: string,        // ISO timestamp of incident start
//   commits: string[],    // Ordered list of commit SHAs (index = commit_order)
//   fail_seq: {[workflow]: number},  // workflow -> commit_order of last failure
//   ok_seq: {[workflow]: number}     // workflow -> commit_order of last success
// }
//
// A workflow is "known failing" iff fail_seq[w] > ok_seq[w]
// Resolution occurs when no workflows are known failing

const STATE_FILE = '.master-ci-incident';

function getCommitOrder(state, sha) {
    const idx = state.commits.indexOf(sha);
    return idx >= 0 ? idx : state.commits.length;
}

function getFailingWorkflows(state) {
    return Object.entries(state.fail_seq)
        .filter(([wf, order]) => order > (state.ok_seq[wf] ?? -1))
        .map(([wf]) => wf);
}

function handleFailure(state, event, order, core, fs) {
    const isNew = !state;

    if (isNew) {
        state = {
            since: new Date().toISOString(),
            commits: [event.head_sha],
            fail_seq: { [event.name]: 0 },
            ok_seq: {},
        };
    } else {
        if (!state.commits.includes(event.head_sha)) {
            state.commits.push(event.head_sha);
        }
        state.fail_seq[event.name] = Math.max(state.fail_seq[event.name] ?? -1, order);
    }

    const failing = getFailingWorkflows(state);
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));

    core.setOutput('action', isNew ? 'create' : 'update');
    core.setOutput('failing_workflows', failing.join(', '));
    core.setOutput('failing_count', String(failing.length));
    core.setOutput('commit_count', String(state.commits.length));
    core.setOutput('save_cache', 'true');

    console.log(`Action: ${isNew ? 'create' : 'update'}`);
    console.log(`Failing workflows: ${failing.join(', ')}`);
    console.log(`State:`, JSON.stringify(state, null, 2));
}

function handleSuccess(state, event, order, core, fs) {
    if (!state) {
        core.setOutput('action', 'none');
        core.setOutput('save_cache', 'false');
        console.log('No incident exists, nothing to do');
        return;
    }

    if (!state.commits.includes(event.head_sha)) {
        state.commits.push(event.head_sha);
    }
    state.ok_seq[event.name] = Math.max(state.ok_seq[event.name] ?? -1, order);

    const failing = getFailingWorkflows(state);
    const resolved = failing.length === 0;

    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));

    core.setOutput('action', resolved ? 'resolve' : 'none');
    core.setOutput('still_failing', failing.join(', '));
    core.setOutput('commit_count', String(state.commits.length));
    core.setOutput('resolved', resolved ? 'true' : 'false');
    core.setOutput('since', state.since);
    core.setOutput('channel', state.channel || '');
    core.setOutput('ts', state.ts || '');
    core.setOutput('save_cache', resolved ? 'false' : 'true');

    console.log(`Action: ${resolved ? 'resolve' : 'none'}`);
    console.log(`Still failing: ${failing.join(', ') || 'none'}`);
    console.log(`State:`, JSON.stringify(state, null, 2));
}

module.exports = async ({ github, context, core }) => {
    const fs = require('fs');
    const event = context.payload.workflow_run;

    console.log(`Processing ${event.name} (${event.conclusion}) for ${event.head_sha.substring(0, 7)}`);

    // Read existing state
    let state = null;
    if (fs.existsSync(STATE_FILE)) {
        try {
            const raw = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
            // Ensure required fields exist (handles old format or corrupted state)
            state = {
                ...raw,
                commits: raw.commits || [],
                fail_seq: raw.fail_seq || {},
                ok_seq: raw.ok_seq || {},
            };
            console.log('Loaded existing incident state');
        } catch (e) {
            console.log('Failed to parse state file, treating as no incident');
        }
    }

    // Get commit order
    const commitOrder = state ? getCommitOrder(state, event.head_sha) : 0;
    console.log(`Commit order: ${commitOrder}`);

    if (event.conclusion === 'failure') {
        handleFailure(state, event, commitOrder, core, fs);
    } else if (event.conclusion === 'success') {
        handleSuccess(state, event, commitOrder, core, fs);
    } else {
        // Ignore cancelled, skipped, etc. - no state change
        core.setOutput('action', 'none');
        core.setOutput('save_cache', 'false');
        console.log(`Ignoring ${event.conclusion} conclusion`);
    }
};
