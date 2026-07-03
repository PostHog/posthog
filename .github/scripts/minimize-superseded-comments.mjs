#!/usr/bin/env node
// Minimizes superseded bot comments on a PR so only the latest of each kind stays
// visible. Some bots post a NEW top-level comment or review on every push instead of
// updating in place — each is correct when posted, but only the newest matters, and
// the pile-up buries the human conversation. The sibling job in this workflow resolves
// outdated bot review THREADS; this covers top-level comments and per-push reviews,
// collapsing the older ones as OUTDATED (still expandable, never deleted).
//
// Best-effort throughout: any fetch or mutation failure warns and moves on — hiding
// stale bot noise is never worth a red check.
//
// Env: GITHUB_TOKEN (or GH_TOKEN), GITHUB_REPOSITORY, PR_NUMBER.

// Keep-newest groups. A comment/review belongs to a group when its author matches and
// its body (leading whitespace ignored) starts with the prefix — bots occasionally pad
// the front of the body with blank lines.
//
// Author logins are the GraphQL form, WITHOUT the "[bot]" suffix — GraphQL reports
// bot authors as e.g. "github-actions" where REST reports "github-actions[bot]".
// Each prefix is coupled to the exact wording the named source emits; if the source
// rewords its message the group silently stops matching, so the zero-match log below
// is the breadcrumb that says a prefix has drifted.
const COMMENT_GROUPS = [
    // stamphog's per-push "kept your approval" notes ("Note retained approval" step
    // in .github/workflows/pr-approval-agent.yml)
    { author: 'github-actions', prefix: 'Retaining stamphog approval' },
    // "branch advanced" skip notices ("Post skip comment" step in
    // .github/actions/commit-snapshots/action.yml)
    { author: 'github-actions', prefix: '⏭️ Skipped snapshot commit' },
]
const REVIEW_GROUPS = [
    // Codex (third-party, wording not ours) posts a fresh review per reviewed commit
    { author: 'chatgpt-codex-connector', prefix: '### 💡 Codex Review' },
]

const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
const repo = process.env.GITHUB_REPOSITORY
const prNumber = Number.parseInt(process.env.PR_NUMBER, 10)
if (!token || !repo || !Number.isFinite(prNumber)) {
    console.warn('Missing GITHUB_TOKEN/GITHUB_REPOSITORY/PR_NUMBER — skipping.')
    process.exit(0)
}
const [owner, name] = repo.split('/')

async function graphql(query, variables) {
    const response = await fetch('https://api.github.com/graphql', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, variables }),
    })
    const payload = await response.json()
    if (!response.ok || payload.errors) {
        throw new Error(`GraphQL failed: ${JSON.stringify(payload.errors ?? payload)}`.slice(0, 500))
    }
    return payload.data
}

async function fetchAll(field) {
    const nodes = []
    let cursor = null
    do {
        const data = await graphql(
            `query($owner: String!, $name: String!, $pr: Int!, $cursor: String) {
                repository(owner: $owner, name: $name) {
                    pullRequest(number: $pr) {
                        ${field}(first: 100, after: $cursor) {
                            pageInfo { hasNextPage endCursor }
                            nodes { id body createdAt isMinimized author { login } }
                        }
                    }
                }
            }`,
            { owner, name, pr: prNumber, cursor }
        )
        const page = data.repository.pullRequest[field]
        nodes.push(...page.nodes)
        cursor = page.pageInfo.hasNextPage ? page.pageInfo.endCursor : null
    } while (cursor)
    return nodes
}

function supersededIn(nodes, groups) {
    const superseded = []
    for (const group of groups) {
        const matches = nodes
            .filter((n) => n.author?.login === group.author && n.body?.trimStart().startsWith(group.prefix))
            .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
        if (matches.length === 0) {
            console.info(`Group "${group.prefix}" matched nothing — fine on most PRs, a drifted prefix if unexpected.`)
            continue
        }
        // Everything but the newest is superseded; already-minimized ones are done.
        superseded.push(...matches.slice(0, -1).filter((n) => !n.isMinimized))
    }
    return superseded
}

let targets = []
try {
    const [comments, reviews] = await Promise.all([fetchAll('comments'), fetchAll('reviews')])
    targets = [...supersededIn(comments, COMMENT_GROUPS), ...supersededIn(reviews, REVIEW_GROUPS)]
} catch (err) {
    console.warn(`Could not fetch PR comments/reviews: ${err.message}`)
    process.exit(0)
}

if (!targets.length) {
    console.info('No superseded bot comments to minimize.')
    process.exit(0)
}

console.info(`Minimizing ${targets.length} superseded bot comment(s)/review(s).`)
for (const target of targets) {
    try {
        await graphql(
            `mutation($id: ID!) {
                minimizeComment(input: { subjectId: $id, classifier: OUTDATED }) {
                    minimizedComment { isMinimized }
                }
            }`,
            { id: target.id }
        )
        console.info(`Minimized ${target.id} (${target.createdAt}).`)
    } catch (err) {
        console.warn(`Could not minimize ${target.id}: ${err.message}`)
    }
}
