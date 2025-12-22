#!/usr/bin/env node

const fs = require('fs')

function parseCodeowners(codeownersPath) {
    if (!fs.existsSync(codeownersPath)) {
        throw new Error(`No CODEOWNERS file found at "${codeownersPath}"`)
    }

    const content = fs.readFileSync(codeownersPath, 'utf8')
    const rules = []

    for (const line of content.split('\n')) {
        const trimmed = line.trim()

        if (!trimmed || trimmed.startsWith('#')) {
            continue
        }

        const tokens = trimmed.split(/\s+/)
        if (tokens.length < 2) {
            continue
        }

        const pattern = tokens[0]
        const owners = tokens.slice(1)

        rules.push({ pattern, owners })
    }

    return rules
}

function globToRegex(pattern) {
    let regex = pattern
        .replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\*\*/g, '__DOUBLESTAR__')
        .replace(/\*/g, '[^/]*')
        .replace(/__DOUBLESTAR__/g, '.*')

    if (pattern.endsWith('/')) {
        regex = regex.slice(0, -1) + '.*'
    }

    return new RegExp(`^${regex}$`)
}

function fileMatchesPattern(filePath, pattern) {
    const regex = globToRegex(pattern)
    return regex.test(filePath)
}

function getNextPageUrl(linkHeader) {
    if (!linkHeader) {
        return null
    }

    for (const link of linkHeader.split(',')) {
        const match = link.match(/<([^>]+)>;\s*rel="next"/)
        if (match) {
            return match[1]
        }
    }

    return null
}

async function getChangedFiles() {
    const { BASE_SHA, HEAD_SHA, GITHUB_TOKEN, GITHUB_REPOSITORY } = process.env
    const allFiles = []
    let url = `https://api.github.com/repos/${GITHUB_REPOSITORY}/compare/${BASE_SHA}...${HEAD_SHA}?per_page=100`

    while (url) {
        const response = await fetch(url, {
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
            },
        })

        if (!response.ok) {
            const errorText = await response.text()
            throw new Error(`GitHub API error: ${response.status} ${response.statusText}\n${errorText}`)
        }

        const data = await response.json()
        for (const file of data.files || []) {
            allFiles.push(file.filename)
        }

        url = getNextPageUrl(response.headers.get('Link'))
    }

    return allFiles
}

function parseOwners(owners) {
    const teams = new Set()
    const users = new Set()

    for (const owner of owners) {
        if (owner.startsWith('@PostHog/')) {
            const teamName = owner.replace('@PostHog/', '')
            teams.add(teamName)
        } else if (owner.startsWith('@')) {
            const username = owner.replace('@', '')
            users.add(username)
        }
    }

    return {
        teams: Array.from(teams),
        users: Array.from(users),
    }
}

async function getReviewersForChangedFiles() {
    const codeownersPath = '.github/CODEOWNERS-soft'
    const rules = parseCodeowners(codeownersPath)
    const changedFiles = await getChangedFiles()

    console.info(`Found ${changedFiles.length} changed files:`)
    changedFiles.forEach((file) => console.info(`  ${file}`))
    console.info()

    const allTeams = new Set()
    const allUsers = new Set()

    console.info('Processing CODEOWNERS rules...')

    for (const rule of rules) {
        const { pattern, owners } = rule
        console.info(`Checking pattern: ${pattern}`)

        let patternMatches = false

        for (const file of changedFiles) {
            if (fileMatchesPattern(file, pattern)) {
                console.info(`  ✓ File ${file} matches pattern ${pattern}`)
                patternMatches = true
                break
            }
        }

        if (patternMatches) {
            const { teams, users } = parseOwners(owners)

            console.info(`  Adding owners: ${owners.join(', ')}`)

            teams.forEach((team) => {
                allTeams.add(team)
                console.info(`    Team: ${team}`)
            })

            users.forEach((user) => {
                allUsers.add(user)
                console.info(`    User: ${user}`)
            })
        }
    }

    return {
        teams: Array.from(allTeams),
        users: Array.from(allUsers),
    }
}

async function assignReviewers(teams, users) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env

    if (teams.length === 0 && users.length === 0) {
        console.info('ℹ️  No reviewers to assign')
        return
    }

    const payload = {}

    if (users.length > 0) {
        payload.reviewers = users
    }

    if (teams.length > 0) {
        payload.team_reviewers = teams
    }

    console.info('Assigning reviewers with payload:', JSON.stringify(payload, null, 2))

    const response = await fetch(
        `https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/requested_reviewers`,
        {
            method: 'POST',
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        }
    )

    if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`GitHub API error: ${response.status} ${response.statusText}\n${errorText}`)
    }

    console.info('✅ Reviewers assigned successfully')
}

async function main() {
    const { BASE_SHA, HEAD_SHA, GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env
    const requiredEnvVars = { BASE_SHA, HEAD_SHA, GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER }
    const missing = Object.entries(requiredEnvVars)
        .filter(([, value]) => !value)
        .map(([name]) => name)

    if (missing.length > 0) {
        console.error(`Missing required environment variables: ${missing.join(', ')}`)
        process.exit(1)
    }

    try {
        const { teams, users } = await getReviewersForChangedFiles()

        console.info()
        console.info(`Teams to add: ${teams.join(', ') || 'none'}`)
        console.info(`Users to add: ${users.join(', ') || 'none'}`)
        console.info()

        await assignReviewers(teams, users)
    } catch (error) {
        console.error('Error:', error.message)
        process.exit(1)
    }
}

main()
