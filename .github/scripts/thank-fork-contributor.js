// Runs through actions/github-script when a pull request merges, or from a
// manual dispatch that names a merged pull request to replay. If its body
// carries the hidden marker that the recreating-fork-prs skill writes
// ("<!-- fork-pr: <n> @<login> -->"), it tells the contributor on fork PR #<n>
// where their change landed, then closes that PR.

const THANKS_MARKER = '<!-- fork-contribution-landed -->'
const FORK_PR_MARKER = /<!-- fork-pr: (\d+) @([A-Za-z0-9-]+) -->/
const HANDBOOK_URL = 'https://posthog.com/handbook/engineering/fork-pull-requests'

function parseContribution(body) {
    const match = FORK_PR_MARKER.exec(body || '')
    return match ? { forkPrNumber: Number(match[1]), login: match[2] } : null
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
    return forkPr.comments.nodes.some((comment) => comment.body.includes(THANKS_MARKER))
}

function buildComment({ login, mergedPrNumber, credited }) {
    const coAuthor = credited ? ', with you as co-author' : ''
    return `${THANKS_MARKER}\nThank you for your contribution @${login}! Fork PRs can't run our backend CI, so we merged your change through #${mergedPrNumber}${coAuthor} ([why](${HANDBOOK_URL})).`
}

const MERGED_PR_QUERY = `query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      merged
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

module.exports = async ({ github, context, core, mergedPrNumber }) => {
    const { owner, repo } = context.repo

    const mergedPr = await fetchPullRequest(github, MERGED_PR_QUERY, { owner, name: repo, number: mergedPrNumber })
    // A manual dispatch can name any number, and thanking for an unmerged PR
    // would close the fork PR before its change lands.
    if (!mergedPr?.merged) {
        core.warning(`Skipping #${mergedPrNumber}: not a merged pull request`)
        return
    }
    const contribution = parseContribution(mergedPr.body)
    if (!contribution) {
        core.info(`#${mergedPrNumber} has no fork-pr marker`)
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

module.exports.THANKS_MARKER = THANKS_MARKER
module.exports.parseContribution = parseContribution
module.exports.skipReason = skipReason
module.exports.alreadyTold = alreadyTold
module.exports.buildComment = buildComment
