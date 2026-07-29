// Runs in the token-holding `finalize` job. On success, commits the resolved files onto the PR
// branch; either way, upserts a marker comment recording the attempted (head, master).
//
// Commits go through the GraphQL createCommitOnBranch mutation, not `git push`: GitHub signs them
// (satisfies "require signed commits" with no GPG key), it reuses only the App token, and applying
// file data runs none of the resolved code. Result: one flattened commit on the PR head (master
// isn't an ancestor, which is fine since it doesn't require "branches up to date").

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const repo = process.env.REPO
const result = JSON.parse(readFileSync(process.env.RESULT_JSON, 'utf8'))
const { status, baseOid, masterOid, agentRan, prNumber, headRef, reason, additions, deletions } = result
const usedAgent = agentRan === 'true'

function gh(args, input) {
    return execFileSync('gh', args, { input, encoding: 'utf8' })
}

// The one thing that would let the bot exceed a (trusted, same-repo) author's own permissions is
// signing a commit onto a branch they can't push to — anyone can open a PR *from* a protected
// branch. So refuse to write to one. Everything else rides on same-repo trust: forks never reach
// this workflow (schedule-triggered + head-owner filter), so there's no untrusted input to bind.
let branchProtected = false
try {
    branchProtected = gh(['api', `repos/${repo}/branches/${headRef}`, '--jq', '.protected']).trim() === 'true'
} catch {
    console.log(`::warning::#${prNumber} could not read branch ${headRef}; skipping`)
    process.exit(0)
}

// Bail if the branch advanced since resolve based its work on baseOid — a new tick handles it.
const currentOid = gh(['api', `repos/${repo}/git/ref/heads/${headRef}`, '--jq', '.object.sha']).trim()
if (currentOid !== baseOid) {
    console.log(
        `::warning::#${prNumber} ${headRef} advanced (${baseOid.slice(0, 8)} -> ${currentOid.slice(0, 8)}); skipping`
    )
    process.exit(0)
}

// Format must match the regex in the workflow's detect job.
const marker = `<!-- autoresolve-attempt:${baseOid}:${masterOid} -->`
let committed = null

if (!branchProtected && status === 'resolved' && (additions.length > 0 || deletions.length > 0)) {
    const headline = usedAgent
        ? 'chore: auto-resolve conflicts with master'
        : 'chore: auto-resolve conflicts with master (regenerated artifacts)'
    const mutation = `
      mutation($input: CreateCommitOnBranchInput!) {
        createCommitOnBranch(input: $input) { commit { oid url } }
      }`
    const input = {
        branch: { repositoryNameWithOwner: repo, branchName: headRef },
        expectedHeadOid: baseOid,
        fileChanges: { additions, deletions },
        message: { headline },
    }
    const res = JSON.parse(
        gh(['api', 'graphql', '-f', `query=${mutation}`, '--input', '-'], JSON.stringify({ variables: { input } }))
    )
    committed = res?.data?.createCommitOnBranch?.commit
    if (!committed) {
        console.error('::error::createCommitOnBranch returned no commit')
        console.error(JSON.stringify(res))
        process.exit(1)
    }
    console.log(`Committed ${committed.oid} to ${headRef}: ${committed.url}`)
}

// Sticky comment body: human-readable status + the machine marker that gates re-runs.
let body
if (committed) {
    const how = usedAgent ? 'with an agent' : 'deterministically (regenerated artifacts + preflight)'
    body =
        `🔀 Merged \`master\` and resolved conflicts ${how}.\n\n` +
        `Pushed as a signed commit (${additions.length} file(s) changed). **Review before merging** — ` +
        `auto-resolution is a starting point, not an approval.` +
        (usedAgent
            ? '\n\n> Conflicts needed judgment, so an agent resolved them — give the diff an extra look.'
            : '')
} else if (branchProtected) {
    body =
        `🔒 \`${headRef}\` is a protected branch, so I won't push a resolution onto it — this one needs a human.\n\n` +
        `I won't repeat this until the branch or master moves.`
} else if (status === 'graphite') {
    body =
        `🔀 This is a Graphite stack, so it can't be brought up to date by merging \`master\` — it needs a restack, which only you can do:\n\n` +
        '```\ngt sync\ngt restack\ngt submit --stack\n```\n\n' +
        `Resolve any conflicts Graphite stops on, then \`gt continue\`. I won't repeat this until the branch or master moves.`
} else {
    const why = reason ? ` — ${reason}` : ''
    body =
        `🔀 Tried to auto-resolve conflicts with \`master\` but this one needs a human${why}.\n\n` +
        `I won't retry until the branch or master moves.`
}
body += `\n\n${marker}`

// Upsert: update the existing sticky comment if present, else create one.
const comments = JSON.parse(gh(['api', `repos/${repo}/issues/${prNumber}/comments`, '--paginate']))
const existing = comments.find((c) => c.body?.includes('<!-- autoresolve-attempt:'))
if (existing) {
    gh(['api', '--method', 'PATCH', `repos/${repo}/issues/comments/${existing.id}`, '-f', `body=${body}`])
    console.log(`Updated marker comment on #${prNumber}`)
} else {
    gh(['api', '--method', 'POST', `repos/${repo}/issues/${prNumber}/comments`, '-f', `body=${body}`])
    console.log(`Posted marker comment on #${prNumber}`)
}
