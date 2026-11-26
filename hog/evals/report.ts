// Prints the latest StuntHog result for each hog eval and model, then the criteria that failed.
//
//   bun hog/evals/report.ts
//   bun hog/evals/report.ts --session <id>     # the shell commands and the final message of one session
//   bun hog/evals/report.ts --json > results.json
import { parseArgs } from 'node:util'

const { values } = parseArgs({
    options: {
        url: { type: 'string', default: process.env.STUNTHOG_URL ?? 'http://127.0.0.1:3100' },
        session: { type: 'string' },
        json: { type: 'boolean', default: false },
    },
})

interface Decision {
    criterionDescription: string
    passed: boolean
    feedback: string
}

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
    event: { type: string; toolName?: string; args?: { command?: string } }
}

async function get<T>(path: string): Promise<T> {
    const response = await fetch(new URL(path, values.url))
    if (!response.ok) {
        throw new Error(`GET ${path} answered ${response.status}: ${await response.text()}`)
    }
    return (await response.json()) as T
}

function parsed<T>(value: string | T | null): T | null {
    return typeof value === 'string' ? (JSON.parse(value) as T) : value
}

if (values.session) {
    const events = await get<SessionEvent[]>(`/api/sessions/${values.session}/events`)
    for (const { event } of events) {
        if (event.type === 'tool_execution_start' && event.args?.command) {
            console.info(`$ ${event.args.command}`)
        }
    }
    const session = await get<Session>(`/api/sessions/${values.session}`)
    console.info(`\n${session.agentResult?.text || session.error || '(no final message)'}`)

    process.exit(0)
}

const sessions = (await get<Session[]>('/api/sessions')).filter((session) => session.eval.title.startsWith('hog '))

// The latest session for each eval and model, so a rerun of one model keeps the others in the table.
const latestByModel = new Map<string, Session>()
for (const session of sessions) {
    const key = `${session.evalId} ${session.harness}:${session.model}`
    const seen = latestByModel.get(key)
    if (!seen || seen.createdAt < session.createdAt) {
        latestByModel.set(key, session)
    }
}
const latest = [...latestByModel.values()].sort(
    (a, b) => a.eval.title.localeCompare(b.eval.title) || a.model.localeCompare(b.model)
)

const rows = latest.map((session) => {
    const decisions = parsed<Decision[]>(session.decisions) ?? []
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
