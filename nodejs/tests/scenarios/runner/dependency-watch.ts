import { performance } from 'perf_hooks'
import { setTimeout as sleep } from 'timers/promises'

import type { ProbeFailure } from '../environment/stack'

export type DependencyLoss = {
    name: string
    at: number
    reason: string
    runnerBusy: number
    kind: 'gone' | 'unheard' | 'recovered'
}

type Attempt = { at: number; failures: ProbeFailure[]; runnerBusy: number }

type StepWindow = { scale: number; startedAt: number; endedAt: number }

const RUNNER_BUSY_LIMIT = 0.5
const CONFIRMATIONS_PER_POLL = 2

async function attempt(check: () => Promise<ProbeFailure[]>): Promise<Attempt> {
    const at = Date.now()
    const before = performance.eventLoopUtilization()
    const failures = await check().catch((error: unknown) => [
        { name: 'health check', reason: error instanceof Error ? error.message : String(error), unanswered: false },
    ])
    return { at, failures, runnerBusy: performance.eventLoopUtilization(before).utilization }
}

// The runner hosts the provider edge and runs the probes on its own event loop, so a saturated loop times them
// out against healthy services.
const excused = ({ unanswered }: ProbeFailure, { runnerBusy }: Attempt): boolean =>
    unanswered && runnerBusy >= RUNNER_BUSY_LIMIT

function lossesOf(first: Attempt, second: Attempt): DependencyLoss[] {
    return first.failures.map((failure) => {
        const again = second.failures.find(({ name }) => name === failure.name)
        const kind =
            again === undefined ? 'recovered' : excused(failure, first) && excused(again, second) ? 'unheard' : 'gone'
        const last = again ?? failure
        return {
            name: failure.name,
            at: first.at,
            reason: last.reason,
            runnerBusy: Math.max(first.runnerBusy, second.runnerBusy),
            kind,
        }
    })
}

async function confirmed(check: () => Promise<ProbeFailure[]>): Promise<DependencyLoss[]> {
    const losses: DependencyLoss[] = []
    const confirmations = new Map<string, number>()
    let first = await attempt(check)
    while (first.failures.length > 0) {
        const second = await attempt(check)
        for (const loss of lossesOf(first, second)) {
            losses.push(loss)
            const count = loss.kind === 'recovered' ? (confirmations.get(loss.name) ?? 0) + 1 : CONFIRMATIONS_PER_POLL
            confirmations.set(loss.name, count)
        }
        first = {
            ...second,
            failures: second.failures.filter(({ name }) => (confirmations.get(name) ?? 0) < CONFIRMATIONS_PER_POLL),
        }
    }
    return losses
}

export function watchDependencies(
    check: () => Promise<ProbeFailure[]>,
    everyMs: number
): { stop(): Promise<DependencyLoss[]> } {
    const losses: DependencyLoss[] = []
    const stopped = new AbortController()
    const watching = (async () => {
        while (!stopped.signal.aborted) {
            losses.push(...(await confirmed(check)))
            await sleep(everyMs, undefined, { signal: stopped.signal }).catch(() => undefined)
        }
    })()
    return {
        async stop() {
            stopped.abort()
            await watching
            return losses
        },
    }
}

function whenOf(at: number, steps: readonly StepWindow[]): string {
    const step = steps.find(({ startedAt, endedAt }) => at >= startedAt && at < endedAt)
    if (step) {
        return `in the ${step.scale}x step`
    }
    const time = new Date(at).toISOString()
    return steps.length > 0 && at >= steps[steps.length - 1].endedAt ? `after the drive, at ${time}` : `at ${time}`
}

const firstOfEach = (losses: readonly DependencyLoss[]): DependencyLoss[] =>
    losses.filter((loss, index) => losses.findIndex(({ name }) => name === loss.name) === index)

function goneReasonOf(gone: readonly DependencyLoss[], steps: readonly StepWindow[]): string {
    const each = gone.map(({ name, at, reason }) => `${name} ${whenOf(at, steps)} (${reason})`)
    return `dependencies went away: ${each.join(', ')}`
}

function unheardReasonOf(unheard: readonly DependencyLoss[], steps: readonly StepWindow[]): string {
    const each = unheard.map(({ name, at }) => `${name} ${whenOf(at, steps)}`).join(', ')
    const busy = Math.round(Math.max(...unheard.map(({ runnerBusy }) => runnerBusy)) * 100)
    return `the runner's event loop was too busy to check ${each} (busy ${busy}% of the check), a harness limit: the run cannot tell whether they stayed up`
}

export function dependencyReasonOf(down: readonly DependencyLoss[], steps: readonly StepWindow[]): string | undefined {
    const gone = firstOfEach(down.filter(({ kind }) => kind === 'gone'))
    const unheard = firstOfEach(down.filter(({ kind }) => kind === 'unheard'))
    const reasons = [
        ...(gone.length > 0 ? [goneReasonOf(gone, steps)] : []),
        ...(unheard.length > 0 ? [unheardReasonOf(unheard, steps)] : []),
    ]
    return reasons.length > 0 ? reasons.join('; ') : undefined
}
