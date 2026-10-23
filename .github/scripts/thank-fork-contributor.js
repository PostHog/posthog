// Runs through actions/github-script when a pull request merges. If its body
// carries the line that the recreating-fork-prs skill writes
// ("Contributed by @<login> in #<n>"), it tells the contributor on fork PR #<n>
// where their change landed, then closes that PR.

const MARKER = '<!-- fork-contribution-landed -->'
// Accepts "#123" and a markdown link to ".../pull/123".
const CONTRIBUTION_PATTERN = /Contributed by @([A-Za-z0-9-]+) in (?:#|\[[^\]]*\]\([^)\s]*\/pull\/)(\d+)/
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
    return null
}

function alreadyTold(forkPr) {
    return forkPr.comments.nodes.some((comment) => comment.body.includes(MARKER))
}

function buildComment({ login, mergedPrNumber, credited }) {
    const merged = credited ? `Merged in #${mergedPrNumber}, with you as co-author.` : `Merged in #${mergedPrNumber}.`
    return `${MARKER}\nThanks @${login}! ${merged} Fork PRs can't run our backend CI, so it went in from a branch here ([why](${HANDBOOK_URL})).`
}

const MERGED_PR_QUERY = `query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      body
      mergeCommit { authors(first: 50) { nodes { user { login } } } }
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

async function fetchPullRequest(github, query, variables) {
    try {
        const data = await github.graphql(query, variables)
        return data.repository.pullRequest
    } catch (error) {
        // A number that names an issue or nothing at all is a typo in the PR body, not a job failure.
        if (error.errors?.every((entry) => entry.type === 'NOT_FOUND')) {
            return null
        }
        throw error
    }
}

module.exports = async ({ github, context, core }) => {
    const { owner, repo } = context.repo
    const mergedPrNumber = context.payload.pull_request.number

    const mergedPr = await fetchPullRequest(github, MERGED_PR_QUERY, { owner, name: repo, number: mergedPrNumber })
    const contribution = parseContribution(mergedPr.body)
    if (!contribution) {
        core.info(`#${mergedPrNumber} has no "Contributed by" line`)
        return
    }
    const { login, forkPrNumber } = contribution

    const forkPr = await fetchPullRequest(github, FORK_PR_QUERY, { owner, name: repo, number: forkPrNumber })
    const reason = skipReason(forkPr, login)
    if (reason) {
        core.warning(`Skipping #${forkPrNumber}: ${reason}`)
        return
    }

    if (!alreadyTold(forkPr)) {
        const credited = mergedPr.mergeCommit.authors.nodes.some((author) => sameLogin(author.user?.login, login))
        const body = buildComment({ login, mergedPrNumber, credited })
        await github.rest.issues.createComment({ owner, repo, issue_number: forkPrNumber, body })
        core.info(`Told @${login} on #${forkPrNumber} (credited: ${credited})`)
    }
    if (forkPr.state === 'OPEN') {
        await github.rest.pulls.update({ owner, repo, pull_number: forkPrNumber, state: 'closed' })
        core.info(`Closed #${forkPrNumber}`)
    }
}

module.exports.MARKER = MARKER
module.exports.parseContribution = parseContribution
module.exports.skipReason = skipReason
module.exports.alreadyTold = alreadyTold
module.exports.buildComment = buildComment
