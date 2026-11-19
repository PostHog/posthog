const { execFileSync } = require('node:child_process')

const FORK_PR_MARKER = (number, login) => `<!-- fork-pr: ${number} @${login} -->`
const RECREATED_MARKER = '<!-- fork-pr-recreated -->'
const HANDBOOK_URL = 'https://posthog.com/handbook/engineering/fork-pull-requests'
const MERGE_QUEUE_LABEL = 'trunk-merge-queue-submit'
const WRITE_PERMISSIONS = ['admin', 'maintain', 'write']
const VERDICT_STATES = ['APPROVED', 'CHANGES_REQUESTED', 'DISMISSED']
const PROTECTED_PATH_PREFIXES = ['.github/workflows/', '.depot/workflows/']

class RecreateRefused extends Error {}

function branchName(forkPrNumber) {
    return `fork-pr/${forkPrNumber}`
}

function sameLogin(a, b) {
    return typeof a === 'string' && typeof b === 'string' && a.toLowerCase() === b.toLowerCase()
}

function latestApproval(reviews, login) {
    const verdicts = reviews.filter(
        (review) => sameLogin(review.user?.login, login) && VERDICT_STATES.includes(review.state)
    )
    const latest = verdicts[verdicts.length - 1]
    return latest?.state === 'APPROVED' ? latest : null
}

function noreplyEmail(user) {
    return `${user.id}+${user.login}@users.noreply.github.com`
}

function coAuthorTrailers(commits, contributor) {
    const contributorEmail = noreplyEmail(contributor)
    const seen = new Set([contributorEmail.toLowerCase()])
    const trailers = [`Co-authored-by: ${contributor.name || contributor.login} <${contributorEmail}>`]
    for (const commit of commits) {
        if (commit.parents.length > 1) {
            continue
        }
        const { name, email } = commit.commit.author
        const login = commit.author?.login
        if (sameLogin(login, contributor.login) || seen.has(email.toLowerCase())) {
            continue
        }
        seen.add(email.toLowerCase())
        trailers.push(`Co-authored-by: ${name} <${email}>`)
    }
    return trailers
}

function parseRawDiff(output) {
    const fields = output.split('\0')
    if (fields[fields.length - 1] === '') {
        fields.pop()
    }
    const entries = []
    for (let i = 0; i + 1 < fields.length; i += 2) {
        const [, newMode, , newSha, status] = fields[i].slice(1).split(' ')
        entries.push({ path: fields[i + 1], mode: newMode, sha: newSha, status })
    }
    return entries
}

function protectedPaths(entries) {
    return entries
        .map((entry) => entry.path)
        .filter((path) => PROTECTED_PATH_PREFIXES.some((prefix) => path.startsWith(prefix)))
}

function buildBody({ forkPr, approval, approvedSha, contributor, trailers }) {
    const quoted = (forkPr.body || '_No description._')
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n')
    return [
        FORK_PR_MARKER(forkPr.number, contributor.login),
        RECREATED_MARKER,
        '## Problem',
        '',
        `Contributed by @${contributor.login} in #${forkPr.number}, which cannot merge because backend CI does not run for fork PRs ([why](${HANDBOOK_URL})).`,
        '',
        '## Changes',
        '',
        `The fork PR squashed at ${approvedSha}, the commit @${approval.user.login} approved.`,
        '',
        '<details><summary>Original description</summary>',
        '',
        quoted,
        '',
        '</details>',
        '',
        ...trailers,
    ].join('\n')
}

function git(args, options = {}) {
    return execFileSync('git', args, { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024, ...options })
}

function squashedTree({ masterSha, mergeBaseSha, approvedSha }) {
    git(['fetch', '--no-tags', '--depth=1', '--filter=blob:none', 'origin', masterSha, mergeBaseSha, approvedSha])
    try {
        return git(['merge-tree', '--write-tree', `--merge-base=${mergeBaseSha}`, masterSha, approvedSha])
            .split('\n')[0]
            .trim()
    } catch (error) {
        if (error.status === 1) {
            throw new RecreateRefused(
                'The approved commit conflicts with `master`. Ask the contributor to merge `master` into their branch, approve the new head, then comment `/recreate-fork-pr` again.'
            )
        }
        throw error
    }
}

async function uploadTree({ github, owner, repo, masterTreeSha, entries }) {
    const tree = []
    for (const entry of entries) {
        if (entry.status === 'D') {
            tree.push({ path: entry.path, mode: '100644', type: 'blob', sha: null })
        } else if (entry.mode === '160000') {
            tree.push({ path: entry.path, mode: entry.mode, type: 'commit', sha: entry.sha })
        } else {
            const content = execFileSync('git', ['cat-file', 'blob', entry.sha], { maxBuffer: 256 * 1024 * 1024 })
            const { data: blob } = await github.rest.git.createBlob({
                owner,
                repo,
                content: content.toString('base64'),
                encoding: 'base64',
            })
            tree.push({ path: entry.path, mode: entry.mode, type: 'blob', sha: blob.sha })
        }
    }
    const { data } = await github.rest.git.createTree({ owner, repo, base_tree: masterTreeSha, tree })
    return data.sha
}

async function refuseUnlessAllowed({ github, owner, repo, forkPr, commenter, defaultBranch }) {
    if (forkPr.state !== 'open') {
        throw new RecreateRefused('This pull request is closed.')
    }
    if (forkPr.head.repo?.full_name === `${owner}/${repo}`) {
        throw new RecreateRefused(
            'This pull request is already on a branch in this repository, so CI runs on it as it is.'
        )
    }
    if (forkPr.base.ref !== defaultBranch) {
        throw new RecreateRefused(`Only pull requests into \`${defaultBranch}\` can be re-created.`)
    }
    if (sameLogin(forkPr.user.login, commenter)) {
        throw new RecreateRefused('The author of a pull request cannot re-create it.')
    }
    const { data: permission } = await github.rest.repos.getCollaboratorPermissionLevel({
        owner,
        repo,
        username: commenter,
    })
    if (!WRITE_PERMISSIONS.includes(permission.permission)) {
        throw new RecreateRefused(`@${commenter} does not have write access to this repository.`)
    }
}

async function recreateForkPr({ github, context, core, forkPrNumber, commenter, runUrl }) {
    const { owner, repo } = context.repo
    const { data: repository } = await github.rest.repos.get({ owner, repo })
    const defaultBranch = repository.default_branch
    const { data: forkPr } = await github.rest.pulls.get({ owner, repo, pull_number: forkPrNumber })

    await refuseUnlessAllowed({ github, owner, repo, forkPr, commenter, defaultBranch })

    const reviews = await github.paginate(github.rest.pulls.listReviews, {
        owner,
        repo,
        pull_number: forkPrNumber,
        per_page: 100,
    })
    const approval = latestApproval(reviews, commenter)
    if (!approval) {
        throw new RecreateRefused(
            `@${commenter} has no standing approval on this pull request. Approve the commit you reviewed, then comment \`/recreate-fork-pr\`.`
        )
    }
    const approvedSha = approval.commit_id

    const branch = branchName(forkPrNumber)
    const { data: existing } = await github.rest.pulls.list({ owner, repo, head: `${owner}:${branch}`, state: 'open' })
    if (existing.length > 0) {
        throw new RecreateRefused(`This pull request was already re-created as #${existing[0].number}.`)
    }

    const { data: master } = await github.rest.repos.getBranch({ owner, repo, branch: defaultBranch })
    const masterSha = master.commit.sha
    const { data: comparison } = await github.rest.repos.compareCommitsWithBasehead({
        owner,
        repo,
        basehead: `${masterSha}...${approvedSha}`,
        per_page: 250,
    })
    if (comparison.total_commits > comparison.commits.length) {
        throw new RecreateRefused(
            'The approved commit has more than 250 commits ahead of `master`. Re-create it by hand.'
        )
    }

    const treeSha = squashedTree({ masterSha, mergeBaseSha: comparison.merge_base_commit.sha, approvedSha })
    const entries = parseRawDiff(git(['diff-tree', '-r', '-z', '--no-renames', masterSha, treeSha]))
    if (entries.length === 0) {
        throw new RecreateRefused('The approved commit changes nothing on `master`. It may already have landed.')
    }
    const blocked = protectedPaths(entries)
    if (blocked.length > 0) {
        throw new RecreateRefused(
            `The approved commit changes CI workflows (${blocked.map((path) => `\`${path}\``).join(', ')}). Re-create it by hand so a maintainer owns that change.`
        )
    }

    const { data: contributor } = await github.rest.users.getByUsername({ username: forkPr.user.login })
    const uploadedTreeSha = await uploadTree({
        github,
        owner,
        repo,
        masterTreeSha: master.commit.commit.tree.sha,
        entries,
    })
    const trailers = coAuthorTrailers(comparison.commits, contributor)
    const message = [
        `${forkPr.title} (#${forkPrNumber})`,
        '',
        `Re-created from #${forkPrNumber} at ${approvedSha}.`,
        '',
        ...trailers,
    ]
    const { data: commit } = await github.rest.git.createCommit({
        owner,
        repo,
        message: message.join('\n'),
        tree: uploadedTreeSha,
        parents: [masterSha],
    })
    if (!commit.verification?.verified) {
        throw new Error(
            `GitHub did not sign ${commit.sha} (${commit.verification?.reason}), so the branch ruleset would refuse it`
        )
    }
    await github.rest.git.createRef({ owner, repo, ref: `refs/heads/${branch}`, sha: commit.sha })

    const { data: recreatedPr } = await github.rest.pulls.create({
        owner,
        repo,
        base: defaultBranch,
        head: branch,
        title: forkPr.title,
        body: buildBody({ forkPr, approval, approvedSha, contributor, trailers }),
        maintainer_can_modify: true,
    })
    await github.rest.issues.addLabels({ owner, repo, issue_number: recreatedPr.number, labels: [MERGE_QUEUE_LABEL] })
    await github.rest.pulls.requestReviewers({ owner, repo, pull_number: recreatedPr.number, reviewers: [commenter] })

    const leftBehind =
        forkPr.head.sha !== approvedSha ? ` Commits pushed after ${approvedSha.slice(0, 7)} were not included.` : ''
    await github.rest.issues.createComment({
        owner,
        repo,
        issue_number: forkPrNumber,
        body: `${RECREATED_MARKER}\nThank you @${contributor.login}! Fork PRs can't run our backend CI, so this change continues in #${recreatedPr.number}, with you as co-author ([why](${HANDBOOK_URL})).${leftBehind}\n\n[Run](${runUrl})`,
    })
    await github.rest.pulls.update({ owner, repo, pull_number: forkPrNumber, state: 'closed' })
    core.info(`Re-created #${forkPrNumber} at ${approvedSha} as #${recreatedPr.number}`)
}

module.exports = async ({ github, context, core, forkPrNumber, commenter, runUrl }) => {
    try {
        await recreateForkPr({ github, context, core, forkPrNumber, commenter, runUrl })
    } catch (error) {
        const reason =
            error instanceof RecreateRefused
                ? error.message
                : `Re-creating the pull request failed. See the [run](${runUrl}).`
        await github.rest.issues.createComment({
            ...context.repo,
            issue_number: forkPrNumber,
            body: `@${commenter} ${reason}`,
        })
        core.setFailed(error.message)
    }
}

module.exports.latestApproval = latestApproval
module.exports.coAuthorTrailers = coAuthorTrailers
module.exports.parseRawDiff = parseRawDiff
module.exports.protectedPaths = protectedPaths
module.exports.buildBody = buildBody
