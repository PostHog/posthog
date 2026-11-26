// Prints the latest StuntHog result for each hog eval and model, then the criteria that failed.
//
//   bun hog/evals/report.ts
//   bun hog/evals/report.ts --session <id>     # the shell commands and the final message of one session
//   bun hog/evals/report.ts --json > results.json
import { parseArgs } from 'node:util'
import { z } from 'zod'

import { parseJsonOrUndefined } from '../src/core/json'

const { values } = parseArgs({
    options: {
        url: { type: 'string', default: process.env.STUNTHOG_URL ?? 'http://127.0.0.1:3100' },
        session: { type: 'string' },
        json: { type: 'boolean', default: false },
    },
})

const Decisions = z.array(z.object({ criterionDescription: z.string(), passed: z.boolean(), feedback: z.string() }))
type Decision = z.infer<typeof Decisions>[number]

interface Session {
    id: string
    evalId: string
    model: string
    harness: string
    status: string
    verdict: string | null
    error: string | null
    costUsd: number | null
    durationMs: number | null
    createdAt: string
    eval: { title: string }
    decisions: string | Decision[] | null
    agentResult: { text?: string } | null
}

interface SessionEvent {
    sequence: number
    event: { type: string; toolName?: string; args?: { command?: string } }
}

// StuntHog answers at most this many events at a time, after the sequence number in `after`.
const EVENT_PAGE = 500

async function get<T>(path: string): Promise<T> {
    const response = await fetch(new URL(path, values.url))
    if (!response.ok) {
        throw new Error(`GET ${path} answered ${response.status}: ${await response.text()}`)
    }
    return (await response.json()) as T
}

// StuntHog stores a session's decisions as a JSON string.
function decisionsOf(session: Session): Decision[] {
    const { decisions } = session
    return (typeof decisions === 'string' ? parseJsonOrUndefined(decisions, Decisions) : decisions) ?? []
}

async function sessionEvents(id: string): Promise<SessionEvent[]> {
    const events: SessionEvent[] = []
    for (let after = 0; ; ) {
        const page = await get<SessionEvent[]>(`/api/sessions/${id}/events?after=${after}`)
        events.push(...page)
        const last = page.at(-1)
        if (page.length < EVENT_PAGE || last === undefined) {
            return events
        }
        after = last.sequence
    }
}

if (values.session) {
    const session = await get<Session>(`/api/sessions/${values.session}`)
    // Each harness stores its own native events, and only Pi's carry the command in `args.command`.
    if (session.harness !== 'pi') {
        console.error(`--session prints shell commands for Pi sessions only. This one ran on ${session.harness}.`)
    }

    for (const { event } of await sessionEvents(values.session)) {
        if (event.type === 'tool_execution_start' && event.args?.command) {
            console.info(`$ ${event.args.command}`)
        }
    }
    console.info(`\n${session.agentResult?.text || session.error || '(no final message)'}`)

    process.exit(0)
}

// `/api/sessions` answers only the newest 500 sessions across every eval, so each hog eval is asked for its own.
const hogEvals = (await get<{ id: string; title: string }[]>('/api/evals')).filter((e) => e.title.startsWith('hog '))
const sessions = (
    await Promise.all(hogEvals.map(({ id }) => get<Session[]>(`/api/sessions?evalId=${encodeURIComponent(id)}`)))
).flat()

// The latest judged session for each eval and model, so a rerun of one model keeps the others in the table,
// and a rerun the provider refused at once doesn't hide the last real result.
function isNewer(session: Session, seen: Session): boolean {
    const judged = decisionsOf(session).length > 0
    const seenJudged = decisionsOf(seen).length > 0
    return judged === seenJudged ? seen.createdAt < session.createdAt : judged
}

const latestByModel = new Map<string, Session>()
for (const session of sessions) {
    const key = `${session.evalId} ${session.harness}:${session.model}`
    const seen = latestByModel.get(key)
    if (!seen || isNewer(session, seen)) {
        latestByModel.set(key, session)
    }
}
const latest = [...latestByModel.values()].sort(
    (a, b) => a.eval.title.localeCompare(b.eval.title) || a.model.localeCompare(b.model)
)

const rows = latest.map((session) => {
    const decisions = decisionsOf(session)
    return {
        id: session.id,
        eval: session.eval.title,
        model: `${session.harness}:${session.model}`,
        status: session.status,
        passed: decisions.filter((decision) => decision.passed).length,
        criteria: decisions.length,
        failed: decisions.filter((decision) => !decision.passed),
        costUsd: session.costUsd,
        minutes: session.durationMs === null ? null : session.durationMs / 60_000,
        verdict: session.verdict,
        error: session.error,
    }
})

if (values.json) {
    console.info(JSON.stringify(rows, null, 2))
    process.exit(0)
}

for (const row of rows) {
    const score = row.criteria ? `${row.passed}/${row.criteria}` : row.status
    const cost = row.costUsd === null ? '' : `$${row.costUsd.toFixed(2)}`
    const minutes = row.minutes === null ? '' : `${row.minutes.toFixed(1)} min`
    console.info([row.eval, row.model, score, cost, minutes, row.id].filter(Boolean).join('  '))
    if (row.error) {
        console.info(`    error: ${row.error}`)
    }
    for (const failure of row.failed) {
        console.info(`    failed: ${failure.criterionDescription}`)
    }
}
