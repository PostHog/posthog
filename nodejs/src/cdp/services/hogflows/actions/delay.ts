import { DateTime, DurationLike } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { execHog } from '~/cdp/utils/hog-exec'

import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

export class DelayHandler implements ActionHandler {
    async execute({
        invocation,
        action,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'delay' }>>): Promise<ActionHandlerResult> {
        const nextScheduledAt = action.config.delay_until
            ? await scheduledAtFromInstant(action, invocation)
            : calculatedScheduledAt(
                  action.config.delay_duration ?? '',
                  invocation.state.currentAction?.startedAtTimestamp
              )

        // While the delay is still pending, park WITHOUT advancing currentAction. Advancing eagerly
        // (returning nextAction alongside scheduledAt) made the job look like it was already at the
        // next step for the whole delay, so the subscription matcher could wake it — e.g. when the
        // next step is a wait_until_condition whose event fires — and collapse the delay. Advance only
        // once the delay has elapsed (calculatedScheduledAt returns null).
        if (nextScheduledAt) {
            return { scheduledAt: nextScheduledAt }
        }

        return { nextAction: findContinueAction(invocation) }
    }
}

// Value is expected to be like `10d` or `1.5h` or `10m`

const DURATION_REGEX = /^(\d*\.?\d+)([dhms])$/

// Same shape as a duration, with an optional leading sign so an offset can point before the instant.
const OFFSET_REGEX = /^(-?)(\d*\.?\d+)([dhms])$/

const DEFAULT_MAX_DELAY_UNTIL = '30d'

/** Seconds for a duration string, using the same units and per-unit ceilings as a fixed delay. */
function durationSeconds(value: string): number | null {
    const match = OFFSET_REGEX.exec(value)
    if (!match) {
        return null
    }
    const [, sign, amountString, unit] = match
    const perUnit: Record<string, number> = { d: 86400, h: 3600, m: 60, s: 1 }
    const capped = Math.min(MAX_VALUE_FOR_DURATION_UNIT[unit], parseFloat(amountString))
    return (sign === '-' ? -1 : 1) * capped * perUnit[unit]
}

/** The instant a `delay_until` expression evaluates to, or null when it yields nothing usable. */
function instantFromHogValue(value: unknown): DateTime | null {
    if (value && typeof value === 'object' && '__hogDateTime__' in (value as Record<string, unknown>)) {
        const seconds = (value as { dt?: unknown }).dt
        return typeof seconds === 'number' ? DateTime.fromSeconds(seconds, { zone: 'UTC' }) : null
    }
    if (typeof value === 'number') {
        // Unix seconds, matching toUnixTimestamp(). Milliseconds would put the instant ~50,000 years out,
        // which the max-delay clamp would swallow silently, so reject rather than guess the unit.
        const asSeconds = DateTime.fromSeconds(value, { zone: 'UTC' })
        return asSeconds.isValid ? asSeconds : null
    }
    if (typeof value === 'string') {
        const parsed = DateTime.fromISO(value, { zone: 'UTC' })
        return parsed.isValid ? parsed : null
    }
    return null
}

/**
 * When to continue for a `delay_until` step: the instant its expression evaluates to, plus any offset,
 * clamped to `max_delay_duration` past the step's start. Returns null once that instant has passed.
 *
 * Re-evaluated on every wake rather than only on entry, so a stored date that moves *later* while the run
 * is parked is honoured: the job wakes at the old, earlier instant and re-parks to the new one. A date
 * that moves *earlier* is only noticed once the old instant passes, because the only wake for a parked
 * delay is that stored instant — the subscription matcher never pulls a delay forward. Waking early is
 * free; the step simply re-parks to the new instant.
 */
async function scheduledAtFromInstant(
    action: Extract<HogFlowAction, { type: 'delay' }>,
    invocation: CyclotronJobInvocationHogFlow
): Promise<DateTime | null> {
    const config = action.config.delay_until!
    const startedAtTimestamp = invocation.state.currentAction?.startedAtTimestamp
    if (!startedAtTimestamp) {
        throw new Error("'startedAtTimestamp' is not set or is invalid")
    }

    if (!Array.isArray(config.bytecode) || config.bytecode.length === 0) {
        throw new Error(`Could not read the date to wait for: ${config.bytecode_error ?? 'no compiled expression'}`)
    }

    const globals = { ...invocation.filterGlobals, variables: invocation.state.variables }
    const { execResult, error } = await execHog(config.bytecode, { globals })
    if (error || execResult?.error) {
        throw new Error(`Could not read the date to wait for: ${String(error ?? execResult?.error)}`)
    }

    // A resumed invocation rebuilds its globals from stored state, which can arrive without the event
    // properties the expression reads. Re-evaluating is still worth attempting on every wake, because it is
    // what lets a stored date that moved while parked be honoured — but it must not strand a run that
    // already resolved once, so fall back to the instant recorded on the first park.
    const previous = invocation.state.currentAction?.delayUntilAt
    const instant = instantFromHogValue(execResult?.result) ?? (previous ? DateTime.fromISO(previous) : null)
    if (!instant) {
        // Marked so the run aborts rather than falling through to the next step. on_error defaults to
        // 'continue', which for a "N days before X" message means sending it with nothing to be before.
        if (invocation.state.currentAction) {
            invocation.state.currentAction.delayUntilUnresolved = true
        }
        throw new Error('The date to wait for did not evaluate to a date')
    }
    if (invocation.state.currentAction) {
        invocation.state.currentAction.delayUntilAt = instant.toISO() ?? undefined
    }

    const offsetSeconds = config.offset ? durationSeconds(config.offset) : 0
    if (offsetSeconds === null) {
        throw new Error(`Invalid offset: ${config.offset}`)
    }

    const target = instant.plus({ seconds: offsetSeconds })
    const maxSeconds = durationSeconds(action.config.max_delay_duration ?? DEFAULT_MAX_DELAY_UNTIL)
    const cap = DateTime.fromMillis(startedAtTimestamp)
        .toUTC()
        .plus({ seconds: maxSeconds ?? 0 })
    const scheduledAt = target > cap ? cap : target

    return DateTime.utc() >= scheduledAt ? null : scheduledAt
}

const MAX_VALUE_FOR_DURATION_UNIT: Record<string, number> = {
    d: 30,
    h: 24,
    m: 60,
    s: 60,
}

/**
 * Helper for the common case of delaying a hog flow action.
 * We calculate the delay value and return the scheduleAt based on the time the action started.
 * If an optional value is given of the max delay duration, we will use that instead of the default.
 */
export function calculatedScheduledAt(
    value: string,
    startedAtTimestamp?: number,
    maxDelaySeconds?: number
): DateTime | null {
    const actionStartedAt = startedAtTimestamp ? DateTime.fromMillis(startedAtTimestamp).toUTC() : null

    if (!actionStartedAt || !actionStartedAt.isValid) {
        throw new Error("'startedAtTimestamp' is not set or is invalid")
    }

    const match = DURATION_REGEX.exec(value)

    if (!match) {
        throw new Error(`Invalid duration: ${value}`)
    }

    const [_, amountString, unit] = match

    let duration: DurationLike

    switch (unit) {
        case 'd':
            duration = { days: Math.min(MAX_VALUE_FOR_DURATION_UNIT[unit], parseFloat(amountString)) }
            break
        case 'h':
            duration = { hours: Math.min(MAX_VALUE_FOR_DURATION_UNIT[unit], parseFloat(amountString)) }
            break
        case 'm':
            duration = { minutes: Math.min(MAX_VALUE_FOR_DURATION_UNIT[unit], parseFloat(amountString)) }
            break
        case 's':
            duration = { seconds: Math.min(MAX_VALUE_FOR_DURATION_UNIT[unit], parseFloat(amountString)) }
            break
        default:
            throw new Error(`Invalid duration: ${value}`)
    }

    const waitUntilTime = actionStartedAt.plus(duration)

    if (DateTime.utc().diff(waitUntilTime).as('seconds') > 0) {
        // If the wait until time has already passed, we can just return to indicate no delay is needed
        return null
    }

    if (!maxDelaySeconds) {
        return waitUntilTime
    }

    // If a max delay seconds is provided, we will use that if smaller than the wait until time
    // NOTE: We use `utc` here as this is about clamping the total time for the new schedule, not about a relative time from when the action started
    let scheduledAt = DateTime.utc().plus({ seconds: maxDelaySeconds })

    if (waitUntilTime.diff(scheduledAt).as('seconds') < 0) {
        scheduledAt = waitUntilTime
    }

    return scheduledAt
}
