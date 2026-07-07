#!/usr/bin/env node

const { spawnSync } = require('child_process')
const { pathMatchesPattern } = require('./codeowners')

// Tunable knobs for how aggressively we trim the reviewer list. Kept in one
// place so adjusting noise levels doesn't require re-reading the logic. All
// "lines" values are GitHub's `changes` (additions + deletions) for the files
// an owner actually owns in this diff.
const CONFIG = {
    // Files whose changes are generated or mechanical. They never count toward
    // ownership matching or footprint. A team gains nothing from reviewing a
    // regenerated client or a lockfile bump.
    excludedPatterns: [
        'frontend/src/generated/**',
        'products/*/frontend/generated/**',
        'services/mcp/src/**/generated/**',
        'pnpm-lock.yaml',
        'Cargo.lock',
        'uv.lock',
        '**/*.lock',
        '**/*.snap',
        '**/*.ambr',
        // Regenerated wholesale by `pnpm update-ai-costs` from the OpenRouter API.
        'nodejs/src/ingestion/pipelines/ai/costs/providers/canonical-providers.ts',
        'nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json',
    ],
    // An owner is formally requested for review only if their footprint clears
    // one of these bars; otherwise they are demoted to the explanation comment
    // (still visible, can self-assign, but no review request / queue entry).
    substantiveLines: 10,
    substantiveFiles: 3,
    // Hard ceiling on teams formally requested. If more clear the bar, the
    // smallest-footprint teams are demoted to the comment so a sweeping change
    // can never request a wall of teams.
    maxTeamsRequested: 5,
    // Marker so we update our own comment in place instead of stacking copies.
    commentMarker: '<!-- auto-assign-reviewers -->',
}

// Ownership is resolved by the shared hogli resolver (distributed owners.yaml +
// product.yaml aliases), never re-parsed here — one semantics, many consumers.
// We shell out to its dependency-light JSON entrypoint: pipe the changed
// filenames in, get back `{path: {owners, status, slack, source}}`. The workflow
// provides python3 + pyyaml and checks out master, so the resolver reads the same
// owners.yaml tree CI enforces.
function resolveOwners(filenames) {
    if (filenames.length === 0) {
        return {}
    }
    const python = process.env.OWNERS_RESOLVER_PYTHON || 'python3'
    const pythonPath = process.env.PYTHONPATH
        ? `tools/hogli-commands:${process.env.PYTHONPATH}`
        : 'tools/hogli-commands'
    const result = spawnSync(python, ['-m', 'hogli_commands.owners'], {
        input: filenames.join('\n'),
        encoding: 'utf8',
        env: { ...process.env, PYTHONPATH: pythonPath },
        maxBuffer: 64 * 1024 * 1024,
    })
    if (result.error) {
        throw new Error(`Could not run owners resolver: ${result.error.message}`)
    }
    if (result.status !== 0) {
        throw new Error(`owners resolver exited ${result.status}:\n${result.stderr || result.stdout}`)
    }
    return JSON.parse(result.stdout)
}

// The resolver emits bare team slugs (`team-foo`) and `@handle` individuals.
// Normalize to the CODEOWNERS token shape the rest of the assigner speaks —
// `@PostHog/<slug>` for teams, `@handle` for users — then classify.
function mapResolvedOwner(rawOwner) {
    if (!rawOwner) {
        return null
    }
    const token = rawOwner.startsWith('@') ? rawOwner : `@PostHog/${rawOwner}`
    return classifyOwner(token)
}

// Glob matching lives in the vendored, GitHub-faithful matcher (./codeowners.js,
// a JS port of hmarr/codeowners). Thin wrapper so the rest of the assigner reads
// naturally and the (filePath, pattern) argument order is stable. A malformed
// pattern (e.g. a `***` typo) degrades to "no match" rather than aborting the
// whole run, matching how the vendored CodeOwners class treats batch rules.
function fileMatchesPattern(filePath, pattern) {
    try {
        return pathMatchesPattern(pattern, filePath)
    } catch {
        return false
    }
}

function isExcludedFile(filePath, excludedPatterns = CONFIG.excludedPatterns) {
    return excludedPatterns.some((pattern) => fileMatchesPattern(filePath, pattern))
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
            allFiles.push({
                filename: file.filename,
                // Binary files and pure renames report null counts; treat as 0.
                additions: file.additions || 0,
                deletions: file.deletions || 0,
            })
        }

        url = getNextPageUrl(response.headers.get('Link'))
    }

    return allFiles
}

// On external PRs these teams are labelled instead of requested as reviewers, so
// the team is surfaced without being pulled into the queue before triage. Names
// are the part after `@PostHog/`.
const LABEL_ONLY_TEAMS_FOR_EXTERNAL = new Set(['team-product-analytics'])

// `team-product-analytics` -> `team/product-analytics`; null for non-team owners.
function teamSlugToLabel(name) {
    if (!name || !name.startsWith('team-')) {
        return null
    }
    return name.replace(/^team-/, 'team/')
}

function partitionExternalTeams(teams) {
    const toLabel = teams.filter((name) => LABEL_ONLY_TEAMS_FOR_EXTERNAL.has(name))
    const toRequest = teams.filter((name) => !LABEL_ONLY_TEAMS_FOR_EXTERNAL.has(name))
    return { toLabel, toRequest }
}

// Resolve a raw CODEOWNERS owner token to a kind we can act on, or null if it's
// something we don't assign (e.g. a malformed entry).
function classifyOwner(owner) {
    if (owner.startsWith('@PostHog/')) {
        return { type: 'team', name: owner.replace('@PostHog/', ''), owner }
    }
    if (owner.startsWith('@')) {
        return { type: 'user', name: owner.replace('@', ''), owner }
    }
    return null
}

// Build a footprint per owner from the resolver's per-file result: which
// owners.yaml/product.yaml sources pulled them in, which (non-excluded) files
// they own in this diff, and the total lines changed across those files. Pure
// function; takes the already-fetched files and the resolver map so it's
// trivially testable. `resolutionByPath` maps filename -> {owners, source, ...}.
function computeOwnerFootprints(resolutionByPath, changedFiles, config = CONFIG) {
    const relevantFiles = changedFiles.filter((file) => !isExcludedFile(file.filename, config.excludedPatterns))
    const footprints = new Map()

    for (const file of relevantFiles) {
        const resolution = resolutionByPath[file.filename]
        const owners = (resolution && resolution.owners) || []
        if (owners.length === 0) {
            continue
        }
        // The source is the owners.yaml/product.yaml that decided this file — the
        // actionable locator we surface instead of a glob pattern.
        const source = (resolution && resolution.source) || '(unresolved source)'
        const lines = file.additions + file.deletions

        for (const rawOwner of owners) {
            const resolved = mapResolvedOwner(rawOwner)
            if (!resolved) {
                continue
            }

            let footprint = footprints.get(resolved.owner)
            if (!footprint) {
                footprint = {
                    owner: resolved.owner,
                    type: resolved.type,
                    name: resolved.name,
                    patterns: new Set(), // resolver source locators, shown in the demotion comment
                    files: new Map(), // filename -> changed lines
                }
                footprints.set(resolved.owner, footprint)
            }

            footprint.patterns.add(source)
            footprint.files.set(file.filename, lines)
        }
    }

    return Array.from(footprints.values()).map((footprint) => ({
        owner: footprint.owner,
        type: footprint.type,
        name: footprint.name,
        patterns: Array.from(footprint.patterns),
        fileCount: footprint.files.size,
        lines: Array.from(footprint.files.values()).reduce((sum, n) => sum + n, 0),
    }))
}

function isSubstantive(footprint, config = CONFIG) {
    return footprint.lines >= config.substantiveLines || footprint.fileCount >= config.substantiveFiles
}

// Split matched owners into those we formally request review from vs those we
// only mention in the comment. Rules:
//  - a single matched owner is always requested (never go from 1 owner to 0)
//  - otherwise only owners with a substantive footprint are requested
//  - at least one owner (the largest footprint) is always requested
//  - teams are capped at maxTeamsRequested; the smallest overflow is demoted
function classifyOwners(footprints, config = CONFIG) {
    if (footprints.length === 0) {
        return { requested: [], demoted: [] }
    }

    const byFootprintDesc = (a, b) => b.lines - a.lines || b.fileCount - a.fileCount

    if (footprints.length === 1) {
        return { requested: [...footprints], demoted: [] }
    }

    const requested = []
    const demoted = []
    for (const footprint of footprints) {
        if (isSubstantive(footprint, config)) {
            requested.push(footprint)
        } else {
            demoted.push({ ...footprint, reason: 'minor' })
        }
    }

    // Guarantee at least one reviewer: promote the largest demoted owner.
    if (requested.length === 0) {
        demoted.sort(byFootprintDesc)
        const { reason, ...promoted } = demoted.shift()
        requested.push(promoted)
    }

    // Cap teams: keep the largest, demote the rest. Users are explicit, rare,
    // and intentional, so they're never capped.
    const requestedTeams = requested.filter((f) => f.type === 'team').sort(byFootprintDesc)
    if (requestedTeams.length > config.maxTeamsRequested) {
        const overflow = requestedTeams.slice(config.maxTeamsRequested)
        const overflowOwners = new Set(overflow.map((f) => f.owner))
        for (let i = requested.length - 1; i >= 0; i--) {
            if (overflowOwners.has(requested[i].owner)) {
                demoted.push({ ...requested.splice(i, 1)[0], reason: 'capped' })
            }
        }
    }

    requested.sort(byFootprintDesc)
    demoted.sort(byFootprintDesc)
    return { requested, demoted }
}

function formatPatterns(patterns, max = 3) {
    const shown = patterns.slice(0, max).map((p) => `\`${p}\``)
    if (patterns.length > max) {
        shown.push(`(+${patterns.length - max} more)`)
    }
    return shown.join(', ')
}

// One bullet per skipped owner: the owner (inline code so it doesn't fire an
// @-mention) followed by the matched rule, the one locator worth showing since
// it tells the owner which area pulled them in. Raw file/line counts are
// omitted: without the actual file list (too long to include) a bare "10 files"
// tells the reader nothing actionable.
function formatSkippedOwner(footprint) {
    return `- \`${footprint.owner}\` (${formatPatterns(footprint.patterns, 2)})`
}

// Produce the explanation comment body, or null if no owner was dropped. We
// only post when we actually skipped someone GitHub's "Reviewers" sidebar would
// otherwise have hidden, so the comment carries signal, not noise.
function buildReviewerComment(requested, demoted, config = CONFIG) {
    if (demoted.length === 0) {
        return null
    }

    const allMinor = demoted.every((f) => f.reason === 'minor')
    const reason = allMinor
        ? 'they only have minor changes here'
        : 'their changes are minor, or the reviewer list was getting long'

    return [
        config.commentMarker,
        '### 👀 Auto-assigned reviewers',
        '',
        `These soft owners were skipped because ${reason}. Nothing blocks merge, so self-assign if you'd like a look:`,
        '',
        ...demoted.map(formatSkippedOwner),
        '',
        "Soft owners come from each directory's `owners.yaml` and each product's `product.yaml` " +
            '(resolved nearest-file-wins). The locator after each owner is the file that decided it. ' +
            'Generated files and lockfiles are ignored when deciding ownership.',
    ].join('\n')
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

    const post = (body) =>
        fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/requested_reviewers`, {
            method: 'POST',
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(body),
        })

    const response = await post(payload)

    // GitHub returns 422 for the whole batch if *any* requested team isn't a
    // collaborator on the repo (teams get renamed, deleted, or never set up,
    // owners.yaml and product.yaml drift). Salvage by retrying users +
    // each team independently so valid entries still land, and log the bad
    // slugs so they're visible in the action log as cleanup nudges.
    if (response.status === 422 && teams.length > 0) {
        const errorText = await response.text()
        console.warn(`⚠️  422 on bulk request, retrying individually:\n${errorText}`)

        if (users.length > 0) {
            const r = await post({ reviewers: users })
            if (!r.ok) {
                throw new Error(`GitHub API error assigning users: ${r.status} ${r.statusText}\n${await r.text()}`)
            }
        }

        const dropped = []
        for (const team of teams) {
            const r = await post({ team_reviewers: [team] })
            if (r.status === 422) {
                dropped.push(team)
            } else if (!r.ok) {
                throw new Error(
                    `GitHub API error assigning team '${team}': ${r.status} ${r.statusText}\n${await r.text()}`
                )
            }
        }

        if (dropped.length > 0) {
            console.warn(
                `⚠️  Dropped ${dropped.length} stale team(s): ${dropped.join(', ')}. ` +
                    `Fix product.yaml / owners.yaml so these get assigned next time.`
            )
        }
        console.info('✅ Reviewers assigned (with fallback)')
        return
    }

    if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`GitHub API error: ${response.status} ${response.statusText}\n${errorText}`)
    }

    console.info('✅ Reviewers assigned successfully')
}

// Best-effort: a label failure must never fail the job.
async function applyTeamLabels(labels) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env

    if (labels.length === 0) {
        console.info('ℹ️  No team labels to apply')
        return
    }

    console.info(`Applying team labels: ${labels.join(', ')}`)

    try {
        const response = await fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels`, {
            method: 'POST',
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ labels }),
        })

        if (!response.ok) {
            console.warn(`⚠️  Could not apply team labels: ${response.status} ${response.statusText}`)
            return
        }

        console.info('✅ Team labels applied')
    } catch (error) {
        console.warn(`⚠️  Skipping team labels: ${error.message}`)
    }
}

async function findExistingComment(marker) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env
    let url = `https://api.github.com/repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments?per_page=100`

    while (url) {
        const response = await fetch(url, {
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
            },
        })
        if (!response.ok) {
            throw new Error(`GitHub API error listing comments: ${response.status} ${response.statusText}`)
        }

        const comments = await response.json()
        const existing = comments.find((comment) => comment.body && comment.body.includes(marker))
        if (existing) {
            return existing
        }

        url = getNextPageUrl(response.headers.get('Link'))
    }

    return null
}

// Best-effort: posts/updates the explanation comment. Never throws, since the
// reviewer assignment is the critical path and must not fail because the app
// token lacks `issues: write` or the comments API hiccups.
async function upsertReviewerComment(body) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env

    try {
        const existing = await findExistingComment(CONFIG.commentMarker)
        const url = existing
            ? `https://api.github.com/repos/${GITHUB_REPOSITORY}/issues/comments/${existing.id}`
            : `https://api.github.com/repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments`

        const method = existing ? 'PATCH' : 'POST'
        const response = await fetch(url, {
            method,
            headers: {
                Authorization: `token ${GITHUB_TOKEN}`,
                Accept: 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
            },
            // oxlint-disable-next-line no-invalid-fetch-options -- method is always PATCH/POST, never GET
            body: JSON.stringify({ body }),
        })

        if (response.status === 403) {
            console.warn(
                '⚠️  Could not post the reviewer explanation comment (403). ' +
                    'The assign-reviewers GitHub App needs `issues: write` permission.'
            )
            return
        }
        if (!response.ok) {
            console.warn(`⚠️  Could not post reviewer comment: ${response.status} ${response.statusText}`)
            return
        }

        console.info(existing ? '✅ Reviewer comment updated' : '✅ Reviewer comment posted')
    } catch (error) {
        console.warn(`⚠️  Skipping reviewer comment: ${error.message}`)
    }
}

async function main() {
    const { BASE_SHA, HEAD_SHA, GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env
    const requiredEnvVars = {
        BASE_SHA,
        HEAD_SHA,
        GITHUB_TOKEN,
        GITHUB_REPOSITORY,
        PR_NUMBER,
    }
    const missing = Object.entries(requiredEnvVars)
        .filter(([, value]) => !value)
        .map(([name]) => name)

    if (missing.length > 0) {
        console.error(`Missing required environment variables: ${missing.join(', ')}`)
        process.exit(1)
    }

    try {
        const changedFiles = await getChangedFiles()

        console.info(`Found ${changedFiles.length} changed files:`)
        changedFiles.forEach((file) => console.info(`  ${file.filename} (+${file.additions} -${file.deletions})`))
        console.info()

        // Resolve ownership for the files that actually count (excluded ones can't
        // pull in a reviewer, so don't waste a resolver round-trip on them).
        const relevantFilenames = changedFiles
            .filter((file) => !isExcludedFile(file.filename))
            .map((file) => file.filename)
        const resolutionByPath = resolveOwners(relevantFilenames)

        const footprints = computeOwnerFootprints(resolutionByPath, changedFiles)
        const { requested, demoted } = classifyOwners(footprints)

        const teams = requested.filter((f) => f.type === 'team').map((f) => f.name)
        const users = requested.filter((f) => f.type === 'user').map((f) => f.name)

        // Forks come from external contributors (no write access for same-repo branches).
        const isExternal = process.env.IS_FORK === 'true'

        console.info(`External (fork) PR: ${isExternal}`)
        console.info(`Teams matched: ${teams.join(', ') || 'none'}`)
        console.info(`Users to request: ${users.join(', ') || 'none'}`)
        console.info(`Demoted to comment: ${demoted.map((f) => f.owner).join(', ') || 'none'}`)
        console.info()

        if (!isExternal) {
            await assignReviewers(teams, users)
        } else {
            const { toLabel, toRequest } = partitionExternalTeams(teams)
            await applyTeamLabels(toLabel.map(teamSlugToLabel).filter(Boolean))
            await assignReviewers(toRequest, users)
        }

        const commentBody = buildReviewerComment(requested, demoted)
        if (commentBody) {
            await upsertReviewerComment(commentBody)
        }
    } catch (error) {
        console.error('Error:', error.message)
        process.exit(1)
    }
}

if (require.main === module) {
    main()
}

module.exports = {
    CONFIG,
    isExcludedFile,
    classifyOwner,
    teamSlugToLabel,
    partitionExternalTeams,
    computeOwnerFootprints,
    isSubstantive,
    classifyOwners,
    buildReviewerComment,
    fileMatchesPattern,
}
