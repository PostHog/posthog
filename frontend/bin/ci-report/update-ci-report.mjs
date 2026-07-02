#!/usr/bin/env node
import fs from 'node:fs'

// One sticky comment shared by every CI check that joins it. Each check owns a
// delimited section and updates only its own; the collapsed summary lines and section
// order are rebuilt from the fixed SECTIONS registry every time, so the layout never
// shifts between runs and readers learn where each check lives. Writers may run in
// parallel jobs and workflows: GitHub has no compare-and-set for comment edits, so
// postSection verifies its write survived and retries when a concurrent writer
// clobbered it, and heals duplicate comments left by two writers racing to create.
export const MARKER = '<!-- posthog-ci-report -->'

// The single source of truth for which sections exist and the order they render in.
// Adding a check means adding it here — that is deliberate: it keeps the order a
// reviewed decision rather than an accident of which job happened to write first.
export const SECTIONS = [
    { id: 'bundle-size', title: 'Bundle size' },
    { id: 'eager-graph', title: 'Eager graph' },
    { id: 'dist-size', title: 'Dist folder size' },
    { id: 'mcp-ui-apps', title: 'MCP UI apps size' },
    { id: 'playwright', title: 'Playwright' },
    { id: 'storybook-snapshots', title: 'Storybook snapshots' },
    { id: 'playwright-snapshots', title: 'Playwright snapshots' },
    { id: 'backend-snapshots', title: 'Backend snapshots' },
    { id: 'ai-evals', title: 'AI evals' },
    { id: 'ch-migration-sql', title: 'ClickHouse migration SQL' },
]

export const STATUS_EMOJI = { ok: '✅', warn: '⚠️', fail: '❌', info: 'ℹ️' }

function emojiFor(status) {
    return STATUS_EMOJI[status] ?? STATUS_EMOJI.info
}

function titleFor(id) {
    return SECTIONS.find((s) => s.id === id)?.title ?? id
}

function encodeMeta(meta) {
    return Buffer.from(JSON.stringify(meta), 'utf-8').toString('base64')
}

function decodeMeta(encoded) {
    try {
        return JSON.parse(Buffer.from(encoded, 'base64').toString('utf-8'))
    } catch {
        return {}
    }
}

const SECTION_RE =
    /<!-- ci-report:section:([\w-]+):([A-Za-z0-9+/=]*) -->\n([\s\S]*?)\n<!-- ci-report:section-end:\1 -->/g

// The details wrapper and heading are presentation that renderComment regenerates from
// the marker meta every time, so parsing strips them back off — re-rendering an
// untouched section must never wrap it twice. The greedy body capture matters: section
// bodies can end with their own nested </details>. The heading form covers comments
// written before sections became collapsible.
const RENDERED_INNER_RE = /^<details>\n<summary>.*<\/summary>\n\n([\s\S]*)\n\n<\/details>$/
function stripPresentation(inner) {
    const details = inner.match(RENDERED_INNER_RE)
    if (details) {
        return details[1]
    }
    return inner.replace(/^## .+\n\n/, '')
}

// Parse an existing comment body back into a map of id -> { status, summary, inner }.
// `inner` is the section body as its check posted it; sections this run does not touch
// are re-emitted from it unchanged.
export function parseSections(body) {
    const sections = new Map()
    if (!body) {
        return sections
    }
    for (const match of body.matchAll(SECTION_RE)) {
        const [, id, encodedMeta, inner] = match
        const meta = decodeMeta(encodedMeta)
        sections.set(id, {
            status: meta.status ?? 'info',
            summary: meta.summary ?? '',
            inner: stripPresentation(inner),
        })
    }
    return sections
}

export function upsertSection(sections, { id, status = 'info', summary = '', body }) {
    const next = new Map(sections)
    next.set(id, { status, summary, inner: body })
    return next
}

// Known sections in registry order first, then any unknown ones (from a legacy comment or
// a not-yet-registered check) appended alphabetically so nothing is dropped and order stays
// deterministic across runs.
function orderedIds(sections) {
    const known = SECTIONS.map((s) => s.id).filter((id) => sections.has(id))
    const unknown = [...sections.keys()].filter((id) => !SECTIONS.some((s) => s.id === id)).sort()
    return [...known, ...unknown]
}

// Each section renders as a collapsed <details> block whose summary line carries the
// status, title, and one-line summary — collapsed, the sections ARE the at-a-glance
// list, and the comment stays short no matter how many checks join.
export function renderComment(sections) {
    const ids = orderedIds(sections)
    const blocks = ids.map((id) => {
        const { status, summary: rawSummary, inner } = sections.get(id)
        // The summary renders inline in <summary>…</summary>, which must stay on one line
        // or the strip regex misses the wrapper on re-parse and the section nests another
        // <details> every run. Normalize at the consumption point so summaries replayed
        // from persisted meta are covered as well as freshly upserted ones.
        const summary = String(rawSummary ?? '')
            .replace(/\s+/g, ' ')
            .trim()
        const suffix = summary ? ` — ${summary}` : ''
        return [
            `<!-- ci-report:section:${id}:${encodeMeta({ status, summary })} -->`,
            '<details>',
            `<summary>${emojiFor(status)} <b>${titleFor(id)}</b>${suffix}</summary>`,
            '',
            inner,
            '',
            '</details>',
            `<!-- ci-report:section-end:${id} -->`,
        ].join('\n')
    })
    return [MARKER, '## 🤖 CI report', '', ...blocks].join('\n')
}

export async function gh(token, url, options = {}) {
    const response = await fetch(`https://api.github.com${url}`, {
        ...options,
        headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'application/vnd.github+json',
            'Content-Type': 'application/json',
            ...options.headers,
        },
    })
    if (!response.ok) {
        throw Object.assign(
            new Error(`GitHub API ${options.method || 'GET'} ${url} -> ${response.status}: ${await response.text()}`),
            { status: response.status }
        )
    }
    return response.status === 204 ? null : response.json()
}

// Resolve the PR-comment context from the Actions environment, or null (reason logged)
// when this run cannot comment — missing env or not a pull_request event.
export function resolvePrContext(activity) {
    const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
    const repo = process.env.GITHUB_REPOSITORY
    const eventPath = process.env.GITHUB_EVENT_PATH
    if (!token || !repo || !eventPath) {
        console.info(`Missing GitHub environment (token/repository/event) — skipping ${activity}.`)
        return null
    }
    const prNumber = JSON.parse(fs.readFileSync(eventPath, 'utf-8')).pull_request?.number
    if (!prNumber) {
        console.info(`Not a pull request event — skipping ${activity}.`)
        return null
    }
    return { token, repo, prNumber }
}

export async function listPrComments({ token, repo, prNumber }) {
    const all = []
    for (let page = 1; page <= 50; page++) {
        const comments = await gh(token, `/repos/${repo}/issues/${prNumber}/comments?per_page=100&page=${page}`)
        all.push(...comments)
        if (comments.length < 100) {
            break
        }
    }
    return all
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function sectionEquals(a, b) {
    return !!a && !!b && a.status === b.status && a.summary === b.summary && a.inner === b.inner
}

// Only the report comments this tooling wrote itself. The marker alone is not enough:
// anyone can comment on a public-repo PR, and a human "Quote reply" of the report keeps
// the marker inside `> ` prefixes — matching on substring would adopt, merge, or DELETE
// comments we do not own. The login is the identity behind the `github.token` the
// posting workflow steps pass — moving them to a custom app token changes the login and
// would orphan every existing report comment, so handle that transition here too.
export function isReportComment(comment) {
    return comment.user?.login === 'github-actions[bot]' && comment.body?.startsWith(MARKER)
}

// A concurrent healer racing us can delete the comment between our read and our write —
// that surfaces as a 404 and is retryable. (A concurrent PATCH never 404s; the verify
// pass catches it.) Anything else (403 on a fork's read-only token, 5xx) is not worth
// retrying for a nicety comment.
function isWriteConflict(err) {
    return err.status === 404
}

// Post or update this run's section into the shared comment. Fork PRs run with a
// read-only token, so a failure to read or write is warned and swallowed — the comment
// is a nicety, never worth a red job.
//
// Concurrent writers (other jobs, other workflows) race on the same comment with no
// compare-and-set, so this is read-modify-write plus verify-and-retry: after writing,
// re-read and check this section survived; if a concurrent writer clobbered it (they
// read before our write and wrote after), merge again and rewrite. Two writers racing
// to CREATE the comment can leave duplicates — every attempt merges all report
// comments' sections into the oldest and deletes the rest, writing the merged content
// BEFORE deleting so a cancelled job never loses sections that lived only in a duplicate.
export async function postSection({ id, status, summary, body }, { maxAttempts = 3, retryDelayMs = 1000 } = {}) {
    const context = resolvePrContext('comment')
    if (!context) {
        return
    }
    const { token, repo, prNumber } = context
    // Round-trip the section through render/parse to get the form a re-read returns —
    // renderComment normalizes summaries, so comparing against the raw input would
    // never verify for a summary that needed normalizing.
    const expected = parseSections(renderComment(upsertSection(new Map(), { id, status, summary, body }))).get(id)
    // Jittered so two writers that collided do not retry in lockstep and re-collide on
    // every attempt.
    const backoff = () => sleep(retryDelayMs * (0.5 + Math.random()))

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        let reportComments
        try {
            reportComments = (await listPrComments(context)).filter(isReportComment)
        } catch (err) {
            console.warn(`Could not read PR comments (read-only token on fork PRs?): ${err.message}`)
            return
        }

        const merged = new Map()
        for (const comment of reportComments) {
            for (const [sectionId, section] of parseSections(comment.body)) {
                merged.set(sectionId, section)
            }
        }
        const rendered = renderComment(upsertSection(merged, { id, status, summary, body }))
        const [primary, ...duplicates] = reportComments

        try {
            if (primary) {
                await gh(token, `/repos/${repo}/issues/comments/${primary.id}`, {
                    method: 'PATCH',
                    body: JSON.stringify({ body: rendered }),
                })
            } else {
                await gh(token, `/repos/${repo}/issues/${prNumber}/comments`, {
                    method: 'POST',
                    body: JSON.stringify({ body: rendered }),
                })
            }
        } catch (err) {
            if (isWriteConflict(err)) {
                console.info(`CI report comment changed under section "${id}" — re-reading and retrying.`)
                if (attempt < maxAttempts) {
                    await backoff()
                }
                continue
            }
            console.warn(`Could not post CI report (read-only token on fork PRs?): ${err.message}`)
            return
        }

        for (const duplicate of duplicates) {
            try {
                await gh(token, `/repos/${repo}/issues/comments/${duplicate.id}`, { method: 'DELETE' })
                console.info(`Merged and deleted duplicate CI report comment ${duplicate.id} (PR #${prNumber}).`)
            } catch (err) {
                if (!isWriteConflict(err)) {
                    console.warn(`Could not delete duplicate CI report comment ${duplicate.id}: ${err.message}`)
                }
            }
        }

        try {
            // Success means this section is durable in the primary (oldest) comment —
            // every racing writer converges on the same primary, so that is where a
            // re-read must find it. Healing duplicates is best-effort: a duplicate whose
            // DELETE keeps failing must not burn retries against a write that landed.
            const after = (await listPrComments(context)).filter(isReportComment)
            if (after.length > 0 && sectionEquals(parseSections(after[0].body).get(id), expected)) {
                if (after.length > 1) {
                    console.warn(`CI report still has ${after.length - 1} duplicate comment(s) on PR #${prNumber}.`)
                }
                console.info(`Wrote CI report section "${id}" on PR #${prNumber} (attempt ${attempt}).`)
                return
            }
        } catch (err) {
            console.warn(`Could not verify CI report write: ${err.message}`)
            return
        }

        if (attempt < maxAttempts) {
            console.info(`CI report section "${id}" was clobbered by a concurrent writer — retrying.`)
            await backoff()
        }
    }
    console.warn(
        `Gave up writing CI report section "${id}" after ${maxAttempts} attempts — its next run will restore it.`
    )
}
