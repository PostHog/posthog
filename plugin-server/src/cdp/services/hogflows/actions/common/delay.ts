import { DateTime, DurationLike } from 'luxon'

// Value is expected to be like `10d` or `1.5h` or `10m`

const DURATION_REGEX = /^(\d*\.?\d+)([dhms])$/

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
            duration = { days: parseFloat(amountString) }
            break
        case 'h':
            duration = { hours: parseFloat(amountString) }
            break
        case 'm':
            duration = { minutes: parseFloat(amountString) }
            break
        case 's':
            duration = { seconds: parseFloat(amountString) }
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
