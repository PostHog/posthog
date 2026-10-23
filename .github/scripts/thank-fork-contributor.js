#!/usr/bin/env node

// Runs when a pull request merges. If its body carries the line that the
// recreating-fork-prs skill writes ("Contributed by @<login> in #<n>"), it tells
// the contributor on fork PR #<n> where their change landed, then closes that PR.

const MARKER = '<!-- fork-contribution-landed -->'
const CONTRIBUTION_PATTERN = /Contributed by @([A-Za-z0-9-]+) in #(\d+)/
const HANDBOOK_URL = 'https://posthog.com/handbook/engineering/fork-pull-requests'

function parseContribution(body) {
    const match = CONTRIBUTION_PATTERN.exec(body || '')
    return match ? { login: match[1], forkPrNumber: Number(match[2]) } : null
}

function sameLogin(a, b) {
    return typeof a === 'string' && typeof b === 'string' && a.toLowerCase() === b.toLowerCase()
}

// The merged PR body is written by a maintainer, but a typo in the PR number
// must not post on someone else's pull request.
function skipReason(forkPr, login) {
    if (!forkPr) {
        return 'pull request not found'
    }
    if (!forkPr.isCrossRepository) {
        return 'not opened from a fork'
    }
    if (!sameLogin(forkPr.author?.login, login)) {
        return `opened by ${forkPr.author?.login}, not ${login}`
    }
    if (forkPr.comments.nodes.some((comment) => comment.body.includes(MARKER))) {
        return 'contributor already told'
    }
    return null
}

function buildComment({ login, mergedPrNumber, mergeCommitSha, credited }) {
    const lines = [
        MARKER,
        `Thanks @${login}! Your change landed in #${mergedPrNumber} as ${mergeCommitSha}.`,
        '',
        `Our backend CI does not run pull requests from forks, so a maintainer moved your commits to a branch in this repository after review. [Pull requests from forks](${HANDBOOK_URL}) explains why.`,
    ]
    if (credited) {
        lines.push('', 'GitHub lists you as a co-author of the merged commit.')
    }
    return lines.join('\n')
}

async function github(token, method, path, body) {
    const response = await fetch(`https://api.github.com${path}`, {
        method,
        headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'application/vnd.github+json',
            'Content-Type': 'application/json',
        },
        body: body ? JSON.stringify(body) : undefined,
    })
    if (!response.ok) {
        throw new Error(`${method} ${path} failed: ${response.status} ${await response.text()}`)
    }
    return response.json()
}

async function graphql(token, query, variables) {
    const result = await github(token, 'POST', '/graphql', { query, variables })
    if (result.errors) {
        throw new Error(`GraphQL query failed: ${JSON.stringify(result.errors)}`)
    }
    return result.data.repository.pullRequest
}

const MERGED_PR_QUERY = `query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      body
      mergeCommit { oid authors(first: 50) { nodes { user { login } } } }
    }
  }
}`

const FORK_PR_QUERY = `query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      state
      isCrossRepository
      author { login }
      comments(last: 100) { nodes { body } }
    }
  }
}`

async function main() {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env
    const [owner, name] = GITHUB_REPOSITORY.split('/')
    const mergedPrNumber = Number(PR_NUMBER)

    const mergedPr = await graphql(GITHUB_TOKEN, MERGED_PR_QUERY, { owner, name, number: mergedPrNumber })
    const contribution = parseContribution(mergedPr.body)
    if (!contribution) {
        console.log(`#${mergedPrNumber} has no "Contributed by" line`)
        return
    }
    const { login, forkPrNumber } = contribution

    const forkPr = await graphql(GITHUB_TOKEN, FORK_PR_QUERY, { owner, name, number: forkPrNumber })
    const reason = skipReason(forkPr, login)
    if (reason) {
        console.log(`Skipping #${forkPrNumber}: ${reason}`)
        return
    }

    const credited = mergedPr.mergeCommit.authors.nodes.some((author) => sameLogin(author.user?.login, login))
    const body = buildComment({ login, mergedPrNumber, mergeCommitSha: mergedPr.mergeCommit.oid, credited })
    await github(GITHUB_TOKEN, 'POST', `/repos/${GITHUB_REPOSITORY}/issues/${forkPrNumber}/comments`, { body })
    if (forkPr.state === 'OPEN') {
        await github(GITHUB_TOKEN, 'PATCH', `/repos/${GITHUB_REPOSITORY}/pulls/${forkPrNumber}`, { state: 'closed' })
    }
    console.log(`Told @${login} on #${forkPrNumber} (credited: ${credited})`)
}

if (require.main === module) {
    main().catch((error) => {
        console.error(error)
        process.exit(1)
    })
}

module.exports = { MARKER, parseContribution, skipReason, buildComment }
