#!/usr/bin/env node
import fs from 'node:fs'

// One sticky comment shared by every frontend CI check. Each check owns a delimited
// section and updates only its own; the header list and section order are rebuilt from
// the fixed SECTIONS registry every time, so the layout never shifts between runs and
// readers learn where each check lives. Safe as a plain read-modify-write only because
// every writer runs sequentially in the single frontend-bundle-size job — do not call
// this from parallel jobs without a locking strategy.
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

// GitHub derives a heading anchor by lowercasing, dropping anything that is not a word
// char/space/hyphen, and turning spaces into hyphens. The section headings are plain
// (no emoji), so the same transform yields the anchor the header list links to.
export function slugify(title) {
    return title
        .toLowerCase()
        .replace(/[^\w\s-]/g, '')
        .trim()
        .replace(/\s+/g, '-')
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

// Parse an existing comment body back into a map of id -> { status, summary, inner }.
// `inner` is the rendered section content, kept verbatim so sections this run does not
// touch are re-emitted byte-for-byte.
export function parseSections(body) {
    const sections = new Map()
    if (!body) {
        return sections
    }
    for (const match of body.matchAll(SECTION_RE)) {
        const [, id, encodedMeta, inner] = match
        const meta = decodeMeta(encodedMeta)
        sections.set(id, { status: meta.status ?? 'info', summary: meta.summary ?? '', inner })
    }
    return sections
}

export function upsertSection(sections, { id, status = 'info', summary = '', body }) {
    const next = new Map(sections)
    next.set(id, { status, summary, inner: `## ${titleFor(id)}\n\n${body}` })
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

export function renderComment(sections) {
    const ids = orderedIds(sections)
    const header = ids.map((id) => {
        const { status, summary } = sections.get(id)
        const title = titleFor(id)
        const suffix = summary ? ` — ${summary}` : ''
        return `- ${emojiFor(status)} [${title}](#${slugify(title)})${suffix}`
    })
    const blocks = ids.map((id) => {
        const { status, summary, inner } = sections.get(id)
        return [
            `<!-- ci-report:section:${id}:${encodeMeta({ status, summary })} -->`,
            inner,
            `<!-- ci-report:section-end:${id} -->`,
        ].join('\n')
    })
    return [MARKER, '## 🤖 CI report', '', ...header, '', ...blocks].join('\n')
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
