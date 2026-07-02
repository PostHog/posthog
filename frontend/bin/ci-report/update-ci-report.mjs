#!/usr/bin/env node
import fs from 'node:fs'

// One sticky comment shared by every frontend CI check. Each check owns a delimited
// section and updates only its own; the collapsed summary lines and section order are
// rebuilt from the fixed SECTIONS registry every time, so the layout never shifts
// between runs and readers learn where each check lives. Safe as a plain
// read-modify-write only because every writer runs sequentially in the single
// frontend-bundle-size job — do not call this from parallel jobs without a locking
// strategy.
export const MARKER = '<!-- posthog-ci-report -->'

// The single source of truth for which sections exist and the order they render in.
// Adding a check means adding it here — that is deliberate: it keeps the order a
// reviewed decision rather than an accident of which job happened to write first.
export const SECTIONS = [
    { id: 'bundle-size', title: 'Bundle size' },
    { id: 'eager-graph', title: 'Eager graph' },
    { id: 'dist-size', title: 'Dist folder size' },
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
        const { status, inner } = sections.get(id)
        // The summary renders inline in <summary>…</summary>, which must stay on one line
        // or the strip regex misses the wrapper on re-parse and the section nests another
        // <details> every run. Normalize at the consumption point so summaries replayed
        // from persisted meta are covered as well as freshly upserted ones.
        const summary = String(sections.get(id).summary ?? '')
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
        throw new Error(`GitHub API ${options.method || 'GET'} ${url} -> ${response.status}: ${await response.text()}`)
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

// Post or update this run's section into the shared comment. Fork PRs run with a
// read-only token, so a failure to read or write is warned and swallowed — the comment
// is a nicety, never worth a red job.
export async function postSection({ id, status, summary, body }) {
    const context = resolvePrContext('comment')
    if (!context) {
        return
    }
    const { token, repo, prNumber } = context

    let existing = null
    try {
        existing = (await listPrComments(context)).find((c) => c.body?.includes(MARKER)) ?? null
    } catch (err) {
        console.warn(`Could not read PR comments (read-only token on fork PRs?): ${err.message}`)
        return
    }

    const sections = upsertSection(parseSections(existing?.body ?? ''), { id, status, summary, body })
    const rendered = renderComment(sections)
    try {
        if (existing) {
            await gh(token, `/repos/${repo}/issues/comments/${existing.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ body: rendered }),
            })
            console.info(`Updated CI report section "${id}" on comment ${existing.id} (PR #${prNumber}).`)
        } else {
            await gh(token, `/repos/${repo}/issues/${prNumber}/comments`, {
                method: 'POST',
                body: JSON.stringify({ body: rendered }),
            })
            console.info(`Posted CI report with section "${id}" on PR #${prNumber}.`)
        }
    } catch (err) {
        console.warn(`Could not post CI report (read-only token on fork PRs?): ${err.message}`)
    }
}
