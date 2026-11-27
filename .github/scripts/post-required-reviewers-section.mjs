#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { markdownCell } from '../../frontend/bin/ci-report/format.mjs'
import {
    clearSectionIfPresent,
    gh,
    postSection,
    resolvePrContext,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'required-reviewers'
const MAX_FILES_LISTED = 5
const FILES_PER_PAGE = 100
const MAX_FILE_PAGES = 30

function escapeRegex(text) {
    return text.replace(/[.+^${}()|[\]\\]/g, '\\$&')
}

function globToRegex(glob) {
    let source = ''
    for (let i = 0; i < glob.length; i++) {
        const char = glob[i]
        if (char === '*' && glob[i + 1] === '*') {
            const followedBySlash = glob[i + 2] === '/'
            source += followedBySlash ? '(?:.*/)?' : '.*'
            i += followedBySlash ? 2 : 1
        } else if (char === '*') {
            source += '[^/]*'
        } else if (char === '?') {
            source += '[^/]'
        } else {
            source += escapeRegex(char)
        }
    }
    return source
}

function gitignorePatternToRegex(pattern) {
    let body = pattern
    const directoryOnly = body.endsWith('/')
    if (directoryOnly) {
        body = body.slice(0, -1)
    }
    const anchored = body.includes('/')
    if (body.startsWith('/')) {
        body = body.slice(1)
    }
    const prefix = anchored ? '^' : '^(?:.*/)?'
    const suffix = directoryOnly ? '/.*$' : '(?:/.*)?$'
    return new RegExp(`${prefix}${globToRegex(body)}${suffix}`, 's')
}

export function compileFilePatterns(patterns) {
    const compiled = patterns.map((pattern) => {
        const negated = pattern.startsWith('!')
        return { negated, regex: gitignorePatternToRegex(negated ? pattern.slice(1) : pattern) }
    })
    return (file) => {
        let matched = false
        for (const { negated, regex } of compiled) {
            if (regex.test(file)) {
                matched = !negated
            }
        }
        return matched
    }
}

export function findRequiredReviews(rules, changedFiles) {
    const reviews = []
    for (const rule of rules) {
        if (rule.type !== 'pull_request') {
            continue
        }
        for (const requirement of rule.parameters?.required_reviewers ?? []) {
            if (!(requirement.minimum_approvals > 0)) {
                continue
            }
            const matches = compileFilePatterns(requirement.file_patterns)
            const matched = changedFiles.filter(matches)
            if (matched.length > 0) {
                reviews.push({
                    reviewer: requirement.reviewer,
                    minimumApprovals: requirement.minimum_approvals,
                    files: matched,
                })
            }
        }
    }
    return reviews
}

function describeReviewer(reviewer, teamSlugs, org) {
    if (reviewer.type === 'Team') {
        const slug = teamSlugs.get(reviewer.id)
        return slug ? `\`@${org}/${markdownCell(slug)}\`` : `the team with ID ${reviewer.id}`
    }
    return `${markdownCell(reviewer.type)} ${reviewer.id}`
}

export function buildRequiredReviewersSection(reviews, { baseRef, teamSlugs, org }) {
    if (reviews.length === 0) {
        return null
    }
    const names = reviews.map((review) => describeReviewer(review.reviewer, teamSlugs, org))
    const lines = [
        `The \`${markdownCell(baseRef)}\` branch ruleset requires these approvals because this PR changes files it protects. The expanded merge box shows whether each one is given. The reviewer list shows no code-owner shield for them, and stamphog cannot give them.`,
        '',
    ]
    reviews.forEach((review, index) => {
        const approvals = review.minimumApprovals > 1 ? `${review.minimumApprovals} approvals` : 'an approval'
        const shown = review.files.slice(0, MAX_FILES_LISTED).map((file) => `\`${markdownCell(file)}\``)
        const more = review.files.length > MAX_FILES_LISTED ? ` and ${review.files.length - MAX_FILES_LISTED} more` : ''
        lines.push(`- ${approvals} from ${names[index]}, for ${shown.join(', ')}${more}`)
    })
    return {
        id: SECTION_ID,
        status: 'warn',
        summary: `requires approval from ${names.join(', ')}`,
        body: lines.join('\n'),
    }
}

export async function listChangedFiles({ token, repo, prNumber }, fetchJson = gh) {
    const files = []
    for (let page = 1; page <= MAX_FILE_PAGES; page++) {
        const batch = await fetchJson(token, `/repos/${repo}/pulls/${prNumber}/files?per_page=${FILES_PER_PAGE}&page=${page}`)
        for (const file of batch) {
            files.push(file.filename)
            if (file.previous_filename) {
                files.push(file.previous_filename)
            }
        }
        if (batch.length < FILES_PER_PAGE) {
            return { files, complete: true }
        }
    }
    return { files, complete: false }
}

async function requestedTeamSlugs({ token, repo, prNumber }) {
    try {
        const { teams } = await gh(token, `/repos/${repo}/pulls/${prNumber}/requested_reviewers`)
        return new Map(teams.map((team) => [team.id, team.slug]))
    } catch (err) {
        console.warn(`Could not read requested team reviewers, naming teams by ID: ${err.message}`)
        return new Map()
    }
}

async function postUnchecked(body) {
    await postSection({ id: SECTION_ID, status: 'info', summary: 'not checked on this push', body })
}

async function main() {
    const context = resolvePrContext(`posting "${SECTION_ID}"`)
    if (!context) {
        return
    }
    const baseRef = process.env.BASE_REF
    const org = context.repo.split('/')[0]
    let rules
    let changed
    try {
        rules = await gh(context.token, `/repos/${context.repo}/rules/branches/${encodeURIComponent(baseRef)}`)
        changed = await listChangedFiles(context)
    } catch (err) {
        console.warn(`Could not check ruleset required reviewers: ${err.message}`)
        await postUnchecked('The ruleset or the changed files could not be read on this push. Check the merge box.')
        return
    }
    const reviews = findRequiredReviews(rules, changed.files)
    const section = buildRequiredReviewersSection(reviews, {
        baseRef,
        teamSlugs: await requestedTeamSlugs(context),
        org,
    })
    if (section) {
        await postSection(section)
    } else if (!changed.complete) {
        await postSection({
            id: SECTION_ID,
            status: 'info',
            summary: 'too many files to check',
            body: 'The GitHub API lists at most 3,000 changed files, so this check cannot rule out required reviewers. Check the merge box.',
        })
    } else {
        await clearSectionIfPresent({
            id: SECTION_ID,
            summary: 'no ruleset reviewers needed',
            body: 'This PR no longer changes files that a ruleset assigns to a required reviewer.',
        })
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
