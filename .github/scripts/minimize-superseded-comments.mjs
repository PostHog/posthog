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

// Returns { data, errors } without throwing, so batched mutations can succeed partially.
async function graphqlRaw(query, variables) {
    const response = await fetch('https://api.github.com/graphql', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, variables }),
    })
    const payload = await response.json()
    return { ok: response.ok, data: payload.data, errors: payload.errors }
}

async function graphql(query, variables) {
    const { ok, data, errors } = await graphqlRaw(query, variables)
    if (!ok || errors) {
        throw new Error(`GraphQL failed: ${JSON.stringify(errors ?? data)}`.slice(0, 500))
    }
    return data
}

// One request fetches both comments and reviews (they're sibling fields on the same PR
// node); @include drops a connection from the query once its pages are exhausted, so a PR
// that fits under 100 of each — the common case — costs exactly one round trip.
async function fetchCommentsAndReviews() {
    const comments = []
    const reviews = []
    let needComments = true
    let needReviews = true
    let commentsCursor = null
    let reviewsCursor = null
    while (needComments || needReviews) {
        const data = await graphql(
            `query($owner: String!, $name: String!, $pr: Int!, $commentsCursor: String, $reviewsCursor: String, $needComments: Boolean!, $needReviews: Boolean!) {
                repository(owner: $owner, name: $name) {
                    pullRequest(number: $pr) {
                        comments(first: 100, after: $commentsCursor) @include(if: $needComments) {
                            pageInfo { hasNextPage endCursor }
                            nodes { id body createdAt isMinimized author { login } }
                        }
                        reviews(first: 100, after: $reviewsCursor) @include(if: $needReviews) {
                            pageInfo { hasNextPage endCursor }
                            nodes { id body createdAt isMinimized author { login } }
                        }
                    }
                }
            }`,
            { owner, name, pr: prNumber, commentsCursor, reviewsCursor, needComments, needReviews }
        )
        const pr = data.repository.pullRequest
        if (pr.comments) {
            comments.push(...pr.comments.nodes)
            needComments = pr.comments.pageInfo.hasNextPage
            commentsCursor = pr.comments.pageInfo.endCursor
        }
        if (pr.reviews) {
            reviews.push(...pr.reviews.nodes)
            needReviews = pr.reviews.pageInfo.hasNextPage
            reviewsCursor = pr.reviews.pageInfo.endCursor
        }
    }
    return { comments, reviews }
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
    const { comments, reviews } = await fetchCommentsAndReviews()
    targets = [...supersededIn(comments, COMMENT_GROUPS), ...supersededIn(reviews, REVIEW_GROUPS)]
} catch (err) {
    console.warn(`Could not fetch PR comments/reviews: ${err.message}`)
    process.exit(0)
}

if (!targets.length) {
    console.info('No superseded bot comments to minimize.')
    process.exit(0)
}

// Batch minimizations into aliased mutations so one HTTP request collapses many nodes —
// a comment-heavy first run stops being a per-node request storm (and stays clear of the
// secondary rate limit on content-generating calls). Chunked to keep query complexity
// bounded. GraphQL runs aliased mutations serially and returns partial data on failure,
// so a single bad node warns without dropping the rest of its batch.
const CHUNK = 50
console.info(`Minimizing ${targets.length} superseded bot comment(s)/review(s).`)
for (let start = 0; start < targets.length; start += CHUNK) {
    const batch = targets.slice(start, start + CHUNK)
    const query = `mutation(${batch.map((_, i) => `$id${i}: ID!`).join(', ')}) {
        ${batch
            .map(
                (_, i) =>
                    `m${i}: minimizeComment(input: { subjectId: $id${i}, classifier: OUTDATED }) { minimizedComment { isMinimized } }`
            )
            .join('\n')}
    }`
    const variables = Object.fromEntries(batch.map((t, i) => [`id${i}`, t.id]))
    let result
    try {
        result = await graphqlRaw(query, variables)
    } catch (err) {
        console.warn(`Could not minimize batch of ${batch.length}: ${err.message}`)
        continue
    }
    batch.forEach((target, i) => {
        if (result.data?.[`m${i}`]?.minimizedComment?.isMinimized) {
            console.info(`Minimized ${target.id} (${target.createdAt}).`)
        } else {
            console.warn(`Could not minimize ${target.id}.`)
        }
    })
    if (result.errors) {
        console.warn(`Some minimizations failed: ${JSON.stringify(result.errors).slice(0, 300)}`)
    }
}
