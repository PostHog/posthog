'use strict'

// Helpers that maintain a single PR comment for the feature-flags canary
// lifecycle. The comment is identified by an HTML marker so it survives
// across phases (validation, build, dispatch, rollout, terminal). The
// marker also carries a tiny bit of state (phase, run ids, image, env)
// so a follow-up step can pick up where the previous one left off without
// re-querying everything.

const MARKER = '<!-- pr-canary-status'
const MARKER_RE = /<!--\s*pr-canary-status\s+([^>]*?)-->/
const HOURS_TO_EXPIRY = 48

const PHASES = {
    VALIDATING: { emoji: '🔵', label: 'Validating' },
    BUILDING: { emoji: '🔨', label: 'Building image' },
    DISPATCHED: { emoji: '📨', label: 'Dispatched to charts' },
    ROLLING_OUT: { emoji: '🟡', label: 'Rolling out (no traffic yet)' },
    ROUTING: { emoji: '🟡', label: 'Routing traffic to canary' },
    HEALTHY: { emoji: '🟢', label: 'Healthy', terminal: true },
    CONFLICT: { emoji: '🟠', label: 'Already active for another PR', terminal: true },
    NO_ACTIVE_CANARY: { emoji: '⚪', label: 'No active canary', terminal: true },
    DENIED: { emoji: '🚫', label: 'Denied', terminal: true },
    INVALID_INPUT: { emoji: '⚠️', label: 'Invalid command', terminal: true },
    BUILD_FAILED: { emoji: '🔴', label: 'Build failed', terminal: true },
    FAILED: { emoji: '🔴', label: 'Rollout failed', terminal: true },
    CANCELING: { emoji: '⏳', label: 'Canceling' },
    CANCELED: { emoji: '⚪', label: 'Canceled', terminal: true },
    EXPIRED: { emoji: '⚪', label: 'Expired', terminal: true },
}

const TERMINAL_PHASES = new Set(Object.entries(PHASES).filter(([, v]) => v.terminal).map(([k]) => k))

function isTerminalPhase(phase) {
    return TERMINAL_PHASES.has(phase)
}

function parseMarker(body) {
    if (!body || typeof body !== 'string') return null
    const m = body.match(MARKER_RE)
    if (!m) return null
    const fields = {}
    const re = /(\w+)=(?:"([^"]*)"|(\S+))/g
    let match
    while ((match = re.exec(m[1])) !== null) {
        fields[match[1]] = match[2] !== undefined ? match[2] : match[3]
    }
    return fields
}

const MARKER_KEYS = ['phase', 'pr', 'image', 'env', 'charts_run_id', 'dispatch_run_id']

function renderMarker(meta) {
    const parts = ['pr-canary-status']
    for (const key of MARKER_KEYS) {
        const v = meta[key]
        if (v === undefined || v === null || v === '') continue
        const str = String(v)
        parts.push(/\s/.test(str) ? `${key}="${str.replace(/"/g, '')}"` : `${key}=${str}`)
    }
    return `<!-- ${parts.join(' ')} -->`
}

function relativeTime(iso, now = Date.now()) {
    if (!iso) return null
    const t = new Date(iso).getTime()
    if (!Number.isFinite(t)) return null
    const diff = Math.max(0, now - t)
    if (diff < 60_000) return 'just now'
    const m = Math.floor(diff / 60_000)
    if (m < 60) return `${m} min ago`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}h ${m % 60}m ago`
    const d = Math.floor(h / 24)
    return `${d}d ${h % 24}h ago`
}

function expiresIn(startedAt, now = Date.now(), hoursToExpiry = HOURS_TO_EXPIRY) {
    if (!startedAt) return null
    const start = new Date(startedAt).getTime()
    if (!Number.isFinite(start)) return null
    const remaining = start + hoursToExpiry * 3600 * 1000 - now
    if (remaining <= 0) return 'expired'
    const hours = Math.floor(remaining / 3600_000)
    const mins = Math.floor((remaining % 3600_000) / 60_000)
    return `in ${hours}h ${mins}m`
}

function subcommandsFooter() {
    return [
        '',
        '<sub>Subcommands: `/pr-canary [weight=N] [env=dev|prod-us|prod-eu]` · `/pr-canary cancel` · `/pr-canary status` · `/pr-canary help`</sub>',
    ]
}

function workflowRunsBlock(fields) {
    const links = []
    if (fields.dispatch_run_url) links.push(`- Build & dispatch: [posthog run](${fields.dispatch_run_url})`)
    if (fields.charts_run_url) links.push(`- ArgoCD rollout: [charts run](${fields.charts_run_url})`)
    if (!links.length) return []
    return ['**Workflow runs**', ...links, '']
}

function detailsTable(fields, { includeExpiry } = {}) {
    const rows = []
    if (fields.image) rows.push(['Image', `\`${fields.image}\``])
    if (fields.env) rows.push(['Environment', `\`${fields.env}\``])
    if (fields.weight !== undefined && fields.weight !== null) {
        const w = String(fields.weight)
        const suffix = fields.weight_auto ? ' (auto)' : ''
        rows.push(['Weight', `\`${w}\`${suffix}`])
    }
    if (fields.started_by) rows.push(['Started by', `@${fields.started_by}`])
    if (fields.started_at) {
        const rel = relativeTime(fields.started_at)
        rows.push(['Started', `${rel} (\`${fields.started_at}\`)`])
    }
    if (includeExpiry && fields.started_at) {
        const exp = expiresIn(fields.started_at)
        if (exp) rows.push(['Auto-disables', exp])
    }
    if (!rows.length) return []
    const out = ['| | |', '|---|---|']
    for (const [k, v] of rows) out.push(`| ${k} | ${v} |`)
    out.push('')
    return out
}

function renderBody({ phase, fields = {} }) {
    const def = PHASES[phase] || { emoji: '❔', label: phase }
    const marker = renderMarker({
        phase,
        pr: fields.pr,
        image: fields.image,
        env: fields.env,
        charts_run_id: fields.charts_run_id,
        dispatch_run_id: fields.dispatch_run_id,
    })

    const lines = [marker]

    let header = `### ${def.emoji} Feature-flags canary — ${def.label}`
    if (phase === 'CONFLICT' && fields.holder_pr) {
        header = `### 🟠 Canary already active for #${fields.holder_pr}`
    } else if (phase === 'CANCELED' && fields.canceled_by) {
        header = `### ⚪ Canary canceled by @${fields.canceled_by}`
    } else if ((phase === 'FAILED' || phase === 'BUILD_FAILED') && fields.reason) {
        header = `### 🔴 Canary failed: ${fields.reason}`
    } else if (phase === 'DENIED' && fields.reason) {
        header = `### 🚫 Canary denied: ${fields.reason}`
    } else if (phase === 'INVALID_INPUT' && fields.reason) {
        header = `### ⚠️ Invalid \`/pr-canary\` command: ${fields.reason}`
    }
    lines.push(header, '')

    if (phase === 'CONFLICT') {
        const holderBits = []
        if (fields.env) holderBits.push(`env \`${fields.env}\``)
        if (fields.weight !== undefined && fields.weight !== null) holderBits.push(`weight \`${fields.weight}\``)
        if (fields.holder_actor) holderBits.push(`started by @${fields.holder_actor}`)
        if (fields.started_at) holderBits.push(relativeTime(fields.started_at))
        const expiry = expiresIn(fields.started_at)
        if (expiry) holderBits.push(`expires ${expiry}`)
        const detail = holderBits.length ? ` (${holderBits.join(', ')})` : ''
        lines.push(
            `The feature-flags canary is currently held by **#${fields.holder_pr}**${detail}.`,
            '',
            `Reply \`/pr-canary cancel\` on **#${fields.holder_pr}** to release it, then re-run here. The canary auto-expires after ${HOURS_TO_EXPIRY} hours.`
        )
        lines.push(...subcommandsFooter())
        return lines.join('\n')
    }

    if (phase === 'NO_ACTIVE_CANARY') {
        lines.push('No feature-flags canary is currently active for this PR.')
        lines.push(
            '',
            'Run `/pr-canary` to start one. Optional: `weight=1..10` (or `auto`) and `env=dev|prod-us|prod-eu` (default `dev`).'
        )
        if (fields.dispatch_run_url) lines.push('', `[View workflow run](${fields.dispatch_run_url})`)
        lines.push(...subcommandsFooter())
        return lines.join('\n')
    }

    if (phase === 'DENIED' || phase === 'INVALID_INPUT' || phase === 'BUILD_FAILED' || phase === 'FAILED') {
        if (fields.dispatch_run_url || fields.charts_run_url) {
            lines.push(...workflowRunsBlock(fields))
        }
        lines.push(...subcommandsFooter())
        return lines.join('\n')
    }

    const includeExpiry = ['HEALTHY', 'ROUTING', 'ROLLING_OUT', 'DISPATCHED', 'CANCELING'].includes(phase)
    lines.push(...detailsTable(fields, { includeExpiry }))
    lines.push(...workflowRunsBlock(fields))

    if (phase === 'HEALTHY') {
        lines.push(
            `The canary will auto-disable after ${HOURS_TO_EXPIRY} hours or when the PR is merged/closed.`,
            'Use `/pr-canary cancel` to stop it sooner.',
            ''
        )
    } else if (phase === 'CANCELED') {
        lines.push('All traffic has been routed back to stable pods.', '')
    } else if (phase === 'EXPIRED') {
        lines.push('Canary deployment is no longer active.', '')
    }

    lines.push(...subcommandsFooter())
    return lines.join('\n')
}

async function findExistingComment({ github, owner, repo, prNumber }) {
    const comments = await github.paginate(github.rest.issues.listComments, {
        owner,
        repo,
        issue_number: prNumber,
        per_page: 100,
    })
    return comments.find((c) => c.body && c.body.includes(MARKER)) || null
}

async function upsertStatusComment({ github, context, prNumber, phase, fields = {} }) {
    const owner = context.repo.owner
    const repo = context.repo.repo
    const body = renderBody({ phase, fields: { pr: prNumber, ...fields } })
    const existing = await findExistingComment({ github, owner, repo, prNumber })
    if (existing) {
        await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body })
        return { id: existing.id, created: false }
    }
    const { data: created } = await github.rest.issues.createComment({
        owner,
        repo,
        issue_number: prNumber,
        body,
    })
    return { id: created.id, created: true }
}

module.exports = {
    MARKER,
    PHASES,
    HOURS_TO_EXPIRY,
    isTerminalPhase,
    parseMarker,
    renderMarker,
    renderBody,
    relativeTime,
    expiresIn,
    findExistingComment,
    upsertStatusComment,
}
