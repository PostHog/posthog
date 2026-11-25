import { performance } from 'perf_hooks'
import { setTimeout as sleep } from 'timers/promises'

import { ProbeFailure, hostLimitOf } from '../environment/stack'

export type DependencyLoss = {
    name: string
    at: number
    reason: string
    runnerBusy: number
    kind: 'gone' | 'unheard' | 'host-limit' | 'recovered'
    hostLimit?: string
    sockets?: Record<string, number>
}

type Attempt = { at: number; failures: ProbeFailure[]; runnerBusy: number; unchecked: boolean }

type StepWindow = { scale: number; startedAt: number; endedAt: number }

const RUNNER_BUSY_LIMIT = 0.5
const CONFIRMATIONS_PER_POLL = 2

async function attempt(check: () => Promise<ProbeFailure[]>): Promise<Attempt> {
    const at = Date.now()
    const before = performance.eventLoopUtilization()
    let unchecked = false
    const failures = await check().catch((error: unknown): ProbeFailure[] => {
        unchecked = true
        const hostLimit = hostLimitOf(error)
        const reason = error instanceof Error ? error.message : String(error)
        return [{ name: 'health check', reason, unanswered: false, ...(hostLimit ? { hostLimit } : {}) }]
    })
    return { at, failures, runnerBusy: performance.eventLoopUtilization(before).utilization, unchecked }
}

// The probes run in their own process, but a host busy enough to saturate the runner's loop can still starve that
// process, and the provider edge answers on the runner's own loop. So a probe that ran out its budget without an answer
// while the runner was busy is a harness limit.
const excused = ({ unanswered }: ProbeFailure, { runnerBusy }: Attempt): boolean =>
    unanswered && runnerBusy >= RUNNER_BUSY_LIMIT

const limited = (failure: ProbeFailure, attempt: Attempt): boolean =>
    failure.hostLimit !== undefined || excused(failure, attempt)

function kindOf(
    failure: ProbeFailure,
    again: ProbeFailure | undefined,
    first: Attempt,
    second: Attempt
): DependencyLoss['kind'] {
    if (again === undefined) {
        return 'recovered'
    }
    if (!limited(failure, first) || !limited(again, second)) {
        return 'gone'
    }
    return (failure.hostLimit ?? again.hostLimit) ? 'host-limit' : 'unheard'
}

// The reason quotes the check that supports the verdict: the error of the check that no limit explains for a dependency
// that went away, and the error that showed the host limit, even when the other check only timed out.
function evidenceOf(
    kind: DependencyLoss['kind'],
    failure: ProbeFailure,
    again: ProbeFailure | undefined,
    second: Attempt
): ProbeFailure {
    if (again === undefined) {
        return failure
    }
    if (kind === 'gone') {
        return limited(again, second) ? failure : again
    }
    if (kind === 'host-limit') {
        return again.hostLimit ? again : failure
    }
    return again
}

function lossesOf(first: Attempt, second: Attempt): DependencyLoss[] {
    // A confirming check that failed as a whole heard nothing, so the first check decides each verdict alone. It can
    // show neither that a dependency recovered nor that a busy check's timeout was a loss.
    const confirming = second.unchecked ? first : second
    return first.failures.map((failure) => {
        const again = second.unchecked ? failure : second.failures.find(({ name }) => name === failure.name)
        const kind = kindOf(failure, again, first, confirming)
        const evidence = evidenceOf(kind, failure, again, confirming)
        const { reason, hostLimit } = evidence
        const sockets = evidence.sockets ?? again?.sockets ?? failure.sockets
        return {
            name: failure.name,
            at: first.at,
            reason,
            runnerBusy: Math.max(first.runnerBusy, second.runnerBusy),
            kind,
            ...(hostLimit ? { hostLimit } : {}),
            ...(sockets ? { sockets } : {}),
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

function hostLimitReasonOf(limited: readonly DependencyLoss[], steps: readonly StepWindow[]): string {
    return limited
        .map(
            ({ name, at, reason, hostLimit }) =>
                `the run host ran out of ${hostLimit} to check ${name} ${whenOf(at, steps)} (${reason}), a harness limit: the run cannot tell whether it stayed up`
        )
        .join('; ')
}

export function dependencyReasonOf(down: readonly DependencyLoss[], steps: readonly StepWindow[]): string | undefined {
    const gone = firstOfEach(down.filter(({ kind }) => kind === 'gone'))
    const unheard = firstOfEach(down.filter(({ kind }) => kind === 'unheard'))
    const hostLimited = firstOfEach(down.filter(({ kind }) => kind === 'host-limit'))
    const reasons = [
        ...(gone.length > 0 ? [goneReasonOf(gone, steps)] : []),
        ...(unheard.length > 0 ? [unheardReasonOf(unheard, steps)] : []),
        ...(hostLimited.length > 0 ? [hostLimitReasonOf(hostLimited, steps)] : []),
    ]
    return reasons.length > 0 ? reasons.join('; ') : undefined
}
