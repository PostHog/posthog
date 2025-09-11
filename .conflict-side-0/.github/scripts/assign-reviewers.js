#!/usr/bin/env node

const fs = require('fs')
const { execSync } = require('child_process')

function parseCodeowners(codeownersPath) {
    if (!fs.existsSync(codeownersPath)) {
        console.info('No CODEOWNERS file found')
        return []
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

function getChangedFiles() {
    try {
        const { BASE_SHA, HEAD_SHA } = process.env
        
        if (!BASE_SHA || !HEAD_SHA) {
            console.error('BASE_SHA and HEAD_SHA environment variables are required')
            return []
        }

        const output = execSync(`git diff --name-only ${BASE_SHA}...${HEAD_SHA}`, {
            encoding: 'utf8',
            stdio: ['pipe', 'pipe', 'ignore'],
        })

        return output
            .trim()
            .split('\n')
            .filter((file) => file.length > 0)
    } catch (error) {
        console.error('Failed to get changed files:', error.message)
        return []
    }
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

function getReviewersForChangedFiles() {
    const codeownersPath = '.github/CODEOWNERS-soft'
    const rules = parseCodeowners(codeownersPath)
    const changedFiles = getChangedFiles()

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

    if (!GITHUB_TOKEN || !GITHUB_REPOSITORY || !PR_NUMBER) {
        throw new Error('Missing required environment variables: GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER')
    }

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

    try {
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
    } catch (error) {
        console.error('Failed to assign reviewers:', error.message)
        process.exit(1)
    }
}

async function main() {
    try {
        const { teams, users } = getReviewersForChangedFiles()

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
