#!/usr/bin/env node

// Adds team/feature labels to a PR based on its conventional-commit scope
// (`type(scope): summary`), plus the `docs` label for docs-typed or Inkeep-bot
// PRs, plus the feature flags team's `review/low-hanging-fruit` label (see the
// feature flags team section below). Additive only — it never removes labels, so manual labels and the
// ownership-based labeler (assign-reviewers.js) are left intact.
//
// The scope -> labels mapping lives in .github/auto-assign-labels.json, OUTSIDE
// this script, so the owning team can adjust mappings without changing (and
// re-approving) the workflow or this script. The config is read from the master
// checkout, never the PR, so a fork PR can't inject its own mappings, and the
// PR title only ever selects from a fixed, pre-approved set of labels.

const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

// Anchored to this script's location, not the cwd, so it resolves the same
// whether the workflow runs `node .github/scripts/…` from the repo root or a
// test invokes it from elsewhere.
const DEFAULT_CONFIG_PATH = path.join(__dirname, '..', 'auto-assign-labels.json')

function loadRules(configPath = process.env.CONFIG_PATH || DEFAULT_CONFIG_PATH) {
    if (!fs.existsSync(configPath)) {
        throw new Error(`No label config found at "${configPath}"`)
    }
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8'))
    return Array.isArray(parsed.rules) ? parsed.rules : []
}

// Pull the scope tokens out of a conventional-commit subject: `type(scope): …`.
// Requires the trailing colon so stray parentheses in prose don't match.
// Supports comma-separated scopes (`feat(flags,cohorts):`) and is case-insensitive.
function parseScopes(title) {
    const match = /^\s*\w+\(([^)]+)\)!?:/.exec(title || '')
    if (!match) {
        return []
    }
    return match[1]
        .split(',')
        .map((scope) => scope.trim().toLowerCase())
        .filter(Boolean)
}

// The Inkeep docs bot's login. Its PRs get the `docs` label so the website
// team's project board can exclude them — GitHub project views can't filter by
// author.
const INKEEP_BOT_LOGIN = 'inkeep[bot]'

// Pull the conventional-commit type out of a subject: `type(scope): …` / `type: …`.
// Requires the trailing colon so stray words don't match. Case-insensitive.
function parseType(title) {
    const match = /^\s*(\w+)(\([^)]*\))?!?:/.exec(title || '')
    return match ? match[1].toLowerCase() : null
}

// The `docs` label applies to docs-typed PRs (`docs:` / `docs(scope):`) and to
// anything the Inkeep docs bot opens. Unlike the scope rules, this keys off the
// commit type and the author rather than the scope.
function docsLabelApplies(title, author) {
    return parseType(title) === 'docs' || author === INKEEP_BOT_LOGIN
}

// Map a title's scopes to the de-duplicated labels they should carry.
function labelsForTitle(title, rules) {
    const scopes = new Set(parseScopes(title))
    const labels = new Set()

    for (const rule of rules) {
        if ((rule.scopes || []).some((scope) => scopes.has(String(scope).toLowerCase()))) {
            for (const label of rule.labels || []) {
                labels.add(label)
            }
        }
    }

    return Array.from(labels)
}

// Best-effort: a labeling failure must never fail the job. The workflow does
// nothing but label, so a hard failure would only paint a non-blocking red ✗ on
// the PR over a transient blip or config drift (e.g. a renamed label). We warn
// loudly instead so the cause is visible in the Actions log.
async function addLabels(labels) {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env

    if (labels.length === 0) {
        console.info('ℹ️  Title has no labelable scope; nothing to do')
        return
    }

    console.info(`Adding labels: ${labels.join(', ')}`)

    try {
        // Idempotent: GitHub keeps labels already present, so re-runs on title
        // edits are safe. Additive — we never strip labels that no longer match.
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
            console.warn(
                `⚠️  Could not apply labels: ${response.status} ${response.statusText}\n${await response.text()}`
            )
            return
        }

        console.info('✅ Labels applied')
    } catch (error) {
        // A non-Error throw has no `.message`; fall back to the value itself so
        // the real reason still surfaces in the log.
        console.warn(`⚠️  Skipping labels: ${error?.message ?? error}`)
    }
}

// ---------------------------------------------------------------------------
// Feature flags team only: the `review/low-hanging-fruit` label.
//
// PRs that the PostHog AI app opens for the feature flags team get this label
// when they are quick to review, so the team can pick them off the Feature
// Flags board first. Other teams have not opted in, so everything in this section is scoped to the
// feature flags team. main() calls only flagsLowHangingFruitLabel().
// ---------------------------------------------------------------------------

const FLAGS_LOW_HANGING_FRUIT_LABEL = 'review/low-hanging-fruit'

// The PostHog AI app's login. Its PRs carry the `self-driving` label, but the
// app adds that label a few seconds after it opens the PR, so the `opened`
// payload does not have it yet. The author is set when the PR opens.
const FLAGS_AI_BOT_LOGIN = 'posthog[bot]'

// The label is only for cards on the Feature Flags board. That board auto-adds
// every PR with the team label, so the team label stands in for the board. The
// board is not checked directly for two reasons: this workflow's token cannot
// read organization projects, and the card does not exist yet when the PR opens.
const FLAGS_TEAM_LABEL = 'team/feature-flags'

// Test code cannot break production, so test files do not count toward the
// limits. A tests-only PR therefore qualifies at any size.
const FLAGS_TEST_PATH_PATTERNS = [
    /(^|\/)(tests?|__tests__|__snapshots__)\//,
    /\.(test|spec)\.[cm]?[jt]sx?$/,
    /(^|\/)(test_[^/]*|conftest)\.py$/,
    /_test\.(py|go|rs)$/,
    // Rust test modules that live in `src/`, next to the code they test.
    /(^|\/)(test_[^/]*|tests)\.rs$/,
]

// Components and styles only. A kea logic or a plain `.ts` file holds state and
// API calls, so it is not a UI tweak even when the diff is small.
const FLAGS_UI_PATH_PATTERN = /^(frontend\/src|products\/[^/]+\/frontend)\/.+\.(tsx|scss|css)$/
const FLAGS_KEA_LOGIC_PATTERN = /Logic\.tsx$/

function isFlagsTestFile(filename) {
    return FLAGS_TEST_PATH_PATTERNS.some((pattern) => pattern.test(filename))
}

function isFlagsUiFile(filename) {
    return FLAGS_UI_PATH_PATTERN.test(filename) && !FLAGS_KEA_LOGIC_PATTERN.test(filename)
}

// A PR qualifies when its hand-written, non-test files fit at least one of
// these shapes.
const FLAGS_QUICK_REVIEW_SHAPES = [
    { maxFiles: 2, maxLines: 50, fileMatches: () => true },
    { maxFiles: 5, maxLines: 100, fileMatches: isFlagsUiFile },
]

// GitHub's maximum page size for the "list pull request files" endpoint.
const FLAGS_FILES_PAGE_SIZE = 100

// A small diff in these paths still needs a careful review: a migration changes
// production data, and a workflow change runs with repository secrets.
const FLAGS_RISKY_PATH_PATTERNS = [/(^|\/)migrations\//, /^\.github\//]

function isFlagsLowHangingFruitCandidate(author, labels) {
    return author === FLAGS_AI_BOT_LOGIN && labels.includes(FLAGS_TEAM_LABEL)
}

// Generated files do not count toward the size limits, because nobody reviews
// them line by line. .gitattributes marks them as `linguist-generated`, and git
// reads that file from the master checkout, so the list of generated paths has
// one source of truth. If git fails, all files count, which can only withhold
// the label.
function flagsWithoutGeneratedFiles(files) {
    if (files.length === 0) {
        return files
    }
    try {
        // `-z` separates paths with NUL in the input and output, so a PR file
        // name that contains a newline cannot break the parse.
        const output = execFileSync('git', ['check-attr', '-z', '--stdin', 'linguist-generated'], {
            cwd: path.join(__dirname, '..', '..'),
            input: files.map((file) => file.filename).join('\0'),
        }).toString()
        const fields = output.split('\0')
        const generated = new Set()
        for (let i = 0; i + 2 < fields.length; i += 3) {
            // A bare `linguist-generated` reads as `set`, and the
            // `linguist-generated=true` form reads as `true`.
            if (fields[i + 2] === 'set' || fields[i + 2] === 'true') {
                generated.add(fields[i])
            }
        }
        return files.filter((file) => !generated.has(file.filename))
    } catch (error) {
        console.warn(`⚠️  Could not check for generated files: ${error?.message ?? error}`)
        return files
    }
}

// `files` is the first page of GitHub's "list pull request files" response.
function isFlagsLowHangingFruit(files) {
    // A full page means the PR has at least a page of files, and the files on
    // later pages are not checked. So many files, even generated ones, is not a
    // quick review, so a full page withholds the label.
    if (files.length >= FLAGS_FILES_PAGE_SIZE) {
        return false
    }
    // Check the risky paths before the generated files are removed, because
    // .gitattributes also marks files under `.github/` as generated.
    if (files.some((file) => FLAGS_RISKY_PATH_PATTERNS.some((pattern) => pattern.test(file.filename)))) {
        return false
    }
    const reviewedFiles = flagsWithoutGeneratedFiles(files).filter((file) => !isFlagsTestFile(file.filename))
    const changedLines = reviewedFiles.reduce((sum, file) => sum + file.additions + file.deletions, 0)
    return FLAGS_QUICK_REVIEW_SHAPES.some(
        (shape) =>
            reviewedFiles.length <= shape.maxFiles &&
            changedLines <= shape.maxLines &&
            reviewedFiles.every((file) => shape.fileMatches(file.filename))
    )
}

// The job applies every label after this request, and it has a five-minute
// timeout. A stalled request must give up well before that, so the team and
// docs labels still get applied.
const FLAGS_FILES_REQUEST_TIMEOUT_MS = 10_000

// Fetches only the first page, because isFlagsLowHangingFruit() withholds the
// label when the page is full. Returns null on failure, because a missing size
// must not fail the job or apply the label.
async function fetchFlagsPrFiles() {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER } = process.env

    try {
        const response = await fetch(
            `https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}/files?per_page=${FLAGS_FILES_PAGE_SIZE}`,
            {
                headers: {
                    Authorization: `token ${GITHUB_TOKEN}`,
                    Accept: 'application/vnd.github.v3+json',
                },
                signal: AbortSignal.timeout(FLAGS_FILES_REQUEST_TIMEOUT_MS),
            }
        )

        if (!response.ok) {
            console.warn(`⚠️  Could not list PR files: ${response.status} ${response.statusText}`)
            return null
        }

        return await response.json()
    } catch (error) {
        console.warn(`⚠️  Could not list PR files: ${error?.message ?? error}`)
        return null
    }
}

// Returns the label to add, or null. `labels` are the labels the title rules
// computed for this PR, because the candidate check reads the team label.
async function flagsLowHangingFruitLabel(author, labels) {
    if (!isFlagsLowHangingFruitCandidate(author, labels)) {
        return null
    }
    const files = await fetchFlagsPrFiles()
    return files && isFlagsLowHangingFruit(files) ? FLAGS_LOW_HANGING_FRUIT_LABEL : null
}

// ---------------------------------------------------------------------------
// End of the feature flags team section.
// ---------------------------------------------------------------------------

async function main() {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, PR_TITLE, PR_AUTHOR } = process.env
    const missing = Object.entries({ GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER })
        .filter(([, value]) => !value)
        .map(([name]) => name)

    if (missing.length > 0) {
        console.error(`Missing required environment variables: ${missing.join(', ')}`)
        process.exit(1)
    }

    try {
        const rules = loadRules()
        const labels = labelsForTitle(PR_TITLE, rules)
        if (docsLabelApplies(PR_TITLE, PR_AUTHOR) && !labels.includes('docs')) {
            labels.push('docs')
        }
        const flagsLabel = await flagsLowHangingFruitLabel(PR_AUTHOR, labels)
        if (flagsLabel) {
            labels.push(flagsLabel)
        }
        console.info(`PR title: ${PR_TITLE || '(empty)'}`)
        await addLabels(labels)
    } catch (error) {
        console.error('Error:', error?.message ?? error)
        process.exit(1)
    }
}

if (require.main === module) {
    main()
}

module.exports = {
    parseScopes,
    parseType,
    docsLabelApplies,
    labelsForTitle,
    loadRules,
    isFlagsLowHangingFruitCandidate,
    isFlagsLowHangingFruit,
    flagsWithoutGeneratedFiles,
}
