#!/usr/bin/env node
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
    clearSectionIfPresent,
    gh,
    postSection,
    resolvePrContext,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'required-reviewers'
const MAX_FILES_LISTED = 5

export function findRequiredReviews(rules, changedFiles) {
    const reviews = []
    for (const rule of rules) {
        if (rule.type !== 'pull_request') {
            continue
        }
        for (const requirement of rule.parameters?.required_reviewers ?? []) {
            const matched = changedFiles.filter((file) =>
                requirement.file_patterns.some((pattern) => path.posix.matchesGlob(file, pattern))
            )
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
        return slug ? `\`@${org}/${slug}\`` : `the team with ID ${reviewer.id}`
    }
    return `${reviewer.type} ${reviewer.id}`
}

export function buildRequiredReviewersSection(reviews, { baseRef, teamSlugs, org }) {
    if (reviews.length === 0) {
        return null
    }
    const names = reviews.map((review) => describeReviewer(review.reviewer, teamSlugs, org))
    const lines = [
        `The \`${baseRef}\` branch ruleset requires these approvals because this PR changes files it protects. GitHub shows them only in the expanded merge box, not as code owners in the reviewer list, and stamphog cannot give them.`,
        '',
    ]
    reviews.forEach((review, index) => {
        const approvals = review.minimumApprovals > 1 ? `${review.minimumApprovals} approvals` : 'an approval'
        const shown = review.files.slice(0, MAX_FILES_LISTED).map((file) => `\`${file}\``)
        const more = review.files.length > MAX_FILES_LISTED ? ` and ${review.files.length - MAX_FILES_LISTED} more` : ''
        lines.push(`- ${approvals} from ${names[index]}, for ${shown.join(', ')}${more}`)
    })
    return {
        id: SECTION_ID,
        status: 'warn',
        summary: `needs approval from ${names.join(', ')}`,
        body: lines.join('\n'),
    }
}

async function listChangedFiles({ token, repo, prNumber }) {
    const files = []
    for (let page = 1; page <= 30; page++) {
        const batch = await gh(token, `/repos/${repo}/pulls/${prNumber}/files?per_page=100&page=${page}`)
        for (const file of batch) {
            files.push(file.filename)
            if (file.previous_filename) {
                files.push(file.previous_filename)
            }
        }
        if (batch.length < 100) {
            break
        }
    }
    return files
}

async function requestedTeamSlugs({ token, repo, prNumber }) {
    const { teams } = await gh(token, `/repos/${repo}/pulls/${prNumber}/requested_reviewers`)
    return new Map(teams.map((team) => [team.id, team.slug]))
}

async function main() {
    const context = resolvePrContext(`posting "${SECTION_ID}"`)
    if (!context) {
        return
    }
    const baseRef = process.env.BASE_REF
    const org = context.repo.split('/')[0]
    try {
        const rules = await gh(context.token, `/repos/${context.repo}/rules/branches/${encodeURIComponent(baseRef)}`)
        const reviews = findRequiredReviews(rules, await listChangedFiles(context))
        const section = buildRequiredReviewersSection(reviews, {
            baseRef,
            teamSlugs: await requestedTeamSlugs(context),
            org,
        })
        if (section) {
            await postSection(section)
        } else {
            await clearSectionIfPresent({
                id: SECTION_ID,
                summary: 'no ruleset reviewers needed',
                body: 'This PR no longer changes files that a ruleset assigns to a required reviewer.',
            })
        }
    } catch (err) {
        console.warn(`Could not check ruleset required reviewers: ${err.message}`)
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
