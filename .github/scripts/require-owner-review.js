#!/usr/bin/env node

// Posts the `Owner review` commit status on a PR: red until a team that has opted
// into blocking review has either authored or approved the change.
//
// Why this exists rather than a `.github/CODEOWNERS` entry: GitHub only counts an
// approval from the listed team, and `stamphog[bot]` is a GitHub App, so an App can
// neither be listed nor join a team. A CODEOWNERS entry would therefore hold every
// stamphog-approved PR, including the owning team's own. It also cannot tell whose
// PR it is, so a team gating its product gates itself. The rule here is the one the
// teams actually want: an owning team's own work still merges on a bot approval,
// and everyone else waits for a human from that team.

const { readFileSync } = require('fs')
const { parse } = require('./codeowners')
const { isExcludedFile } = require('./assign-reviewers')

const CONFIG = {
    configPath: '.github/blocking-owners',
    // The name the branch ruleset requires. Changing it silently un-gates every
    // path in the config, because the ruleset then waits on a context nothing posts.
    statusContext: 'Owner review',
    org: 'PostHog',
}

const api = async (path, init = {}) => {
    const url = path.startsWith('https://') ? path : `https://api.github.com${path}`
    const response = await fetch(url, {
        ...init,
        headers: {
            Authorization: `token ${process.env.GITHUB_TOKEN}`,
            Accept: 'application/vnd.github.v3+json',
            ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        },
    })
    if (!response.ok) {
        throw new Error(`${init.method || 'GET'} ${url} -> ${response.status} ${await response.text()}`)
    }
    return response
}

const nextPage = (link) => {
    for (const part of (link || '').split(',')) {
        const match = part.match(/<([^>]+)>;\s*rel="next"/)
        if (match) {
            return match[1]
        }
    }
    return null
}

async function paginate(path) {
    const items = []
    let url = path
    while (url) {
        const response = await api(url)
        items.push(...(await response.json()))
        url = nextPage(response.headers.get('Link'))
    }
    return items
}

// Which opted-in teams own something substantive in this diff. Generated files,
// lockfiles and snapshots are filtered out first: a regenerated client is a
// mechanical diff, and holding it teaches people the status is noise.
function teamsForFiles(configText, filenames) {
    const owners = parse(configText)
    const teams = new Set()
    for (const filename of filenames) {
        if (isExcludedFile(filename)) {
            continue
        }
        for (const owner of owners.ownersOf(filename)) {
            if (owner.startsWith(`@${CONFIG.org}/`)) {
                teams.add(owner.slice(`@${CONFIG.org}/`.length))
            }
        }
    }
    return [...teams].sort()
}

// The whole decision, as a pure function of already-fetched facts.
// `membersByTeam` maps slug -> Set of logins.
function evaluate({ teams, authorLogin, approvers, membersByTeam }) {
    const satisfied = []
    const missing = []
    for (const team of teams) {
        const members = membersByTeam.get(team) || new Set()
        if (members.has(authorLogin) || [...approvers].some((login) => members.has(login))) {
            satisfied.push(team)
        } else {
            missing.push(team)
        }
    }
    if (teams.length === 0) {
        return { state: 'success', missing, description: 'No path in this PR needs an owner review' }
    }
    if (missing.length === 0) {
        return { state: 'success', missing, description: `Covered by ${satisfied.join(', ')}` }
    }
    return {
        state: 'failure',
        missing,
        description: `Needs an approval from ${missing.join(', ')}`,
    }
}

// The last review each person left, so a dismissed or superseded approval does not
// keep counting. Bots are kept in the list on purpose: a bot that joins the team is
// impossible today, so they simply never match a roster.
function latestApprovers(reviews) {
    const lastState = new Map()
    for (const review of reviews) {
        if (['APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'].includes(review.state)) {
            lastState.set(review.user.login, review.state)
        }
    }
    return new Set([...lastState].filter(([, state]) => state === 'APPROVED').map(([login]) => login))
}

async function teamMembers(slug) {
    const members = await paginate(`/orgs/${CONFIG.org}/teams/${slug}/members?per_page=100`)
    return new Set(members.map((member) => member.login))
}

async function postStatus({ state, description }) {
    const { GITHUB_REPOSITORY, HEAD_SHA, GITHUB_SERVER_URL, GITHUB_RUN_ID } = process.env
    await api(`/repos/${GITHUB_REPOSITORY}/statuses/${HEAD_SHA}`, {
        method: 'POST',
        body: JSON.stringify({
            state,
            context: CONFIG.statusContext,
            // GitHub truncates at 140 characters and shows nothing instead of erroring.
            description: description.slice(0, 140),
            target_url: `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}`,
        }),
    })
    console.info(`${state}: ${description}`)
}

async function main() {
    const { GITHUB_REPOSITORY, PR_NUMBER, HEAD_SHA, GITHUB_TOKEN } = process.env
    const missingEnv = Object.entries({ GITHUB_REPOSITORY, PR_NUMBER, HEAD_SHA, GITHUB_TOKEN })
        .filter(([, value]) => !value)
        .map(([name]) => name)
    if (missingEnv.length > 0) {
        console.error(`Missing required environment variables: ${missingEnv.join(', ')}`)
        process.exit(1)
    }

    const pr = await (await api(`/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}`)).json()
    const files = await paginate(`/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/files?per_page=100`)
    const teams = teamsForFiles(
        readFileSync(CONFIG.configPath, 'utf8'),
        files.map((file) => file.filename)
    )
    console.info(`Teams that gate this diff: ${teams.join(', ') || 'none'}`)

    const membersByTeam = new Map()
    for (const team of teams) {
        membersByTeam.set(team, await teamMembers(team))
    }
    const approvers = latestApprovers(
        await paginate(`/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100`)
    )
    console.info(`Approved by: ${[...approvers].join(', ') || 'nobody'}`)

    await postStatus(evaluate({ teams, authorLogin: pr.user.login, approvers, membersByTeam }))
}

if (require.main === module) {
    main().catch(async (error) => {
        console.error(error.message)
        // A red status on an API failure, rather than a green one: this gate is only
        // worth having if it fails closed. Re-run the job once the cause is fixed.
        try {
            await postStatus({ state: 'error', description: `Could not evaluate owner review: ${error.message}` })
        } catch (statusError) {
            console.error(`Could not post the status either: ${statusError.message}`)
        }
        process.exit(1)
    })
}

module.exports = { CONFIG, teamsForFiles, evaluate, latestApprovers }
