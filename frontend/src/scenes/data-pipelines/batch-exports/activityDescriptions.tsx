import {
    ActivityChange,
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { dayOptions, formatHourString } from './utils'

const nameOrLinkToBatchExport = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(unnamed export)'
    return id ? <Link to={urls.batchExport(id)}>{displayName}</Link> : `${displayName}`
}

// ---------------------------------------------------------------------------
// Schedule display helpers
// ---------------------------------------------------------------------------

const SCHEDULE_FIELDS = new Set(['interval', 'interval_offset', 'timezone'])

interface ScheduleValues {
    interval?: string
    offset?: number
    timezone?: string
}

function parseScheduleChanges(changes: ActivityChange[]): {
    before: ScheduleValues
    after: ScheduleValues
    hasIntervalChange: boolean
} {
    const before: ScheduleValues = {}
    const after: ScheduleValues = {}
    let hasIntervalChange = false

    for (const change of changes) {
        switch (change.field) {
            case 'interval':
                hasIntervalChange = true
                if (typeof change.before === 'string') {
                    before.interval = change.before
                }
                if (typeof change.after === 'string') {
                    after.interval = change.after
                }
                break
            case 'interval_offset':
                // null means default (midnight), so treat as 0
                before.offset = typeof change.before === 'number' ? change.before : 0
                after.offset = typeof change.after === 'number' ? change.after : 0
                break
            case 'timezone':
                if (typeof change.before === 'string') {
                    before.timezone = change.before
                }
                if (typeof change.after === 'string') {
                    after.timezone = change.after
                }
                break
        }
    }

    return { before, after, hasIntervalChange }
}

function isSubDayInterval(interval: string | undefined): boolean {
    return interval === 'hour' || (!!interval && interval.startsWith('every'))
}

function formatOffsetTime(seconds: number): string {
    return formatHourString(Math.floor((seconds % 86400) / 3600))
}

/**
 * Build a human-readable schedule string from typed schedule values.
 * Examples: "hourly", "daily at 14:00 (Asia/Muscat)", "weekly on Monday at 01:00 (UTC)"
 */
export function formatSchedule(interval: string | undefined, offset?: number, timezone?: string): string | null {
    if (!interval) {
        return null
    }

    if (isSubDayInterval(interval)) {
        return interval === 'hour' ? 'hourly' : interval
    }

    let schedule = interval === 'day' ? 'daily' : interval === 'week' ? 'weekly' : interval

    if (offset !== undefined) {
        const day = Math.floor(offset / 86400)
        const hourStr = formatOffsetTime(offset)

        if (interval === 'week') {
            const dayName = dayOptions.find((d) => d.value === day)?.label ?? dayOptions[0].label
            schedule += ` on ${dayName} at ${hourStr}`
        } else {
            schedule += ` at ${hourStr}`
        }
    }

    if (timezone) {
        schedule += ` (${timezone})`
    }

    return schedule
}

/**
 * Produce descriptions for schedule-related changes.
 *
 * When the interval changes, we combine all schedule fields into one "schedule" description
 * (e.g. "changed schedule from hourly to daily at 14:00 (UTC)").
 *
 * When only timezone or start time changes (no interval change), we describe them individually
 * since we don't have enough context to build a full schedule string.
 */
function describeScheduleChanges(scheduleChanges: ActivityChange[]): ChangeDescription[] {
    if (scheduleChanges.length === 0) {
        return []
    }

    const { before, after, hasIntervalChange } = parseScheduleChanges(scheduleChanges)

    // When the interval changes, combine everything into a single "schedule" description
    if (hasIntervalChange) {
        // When coming from a sub-day interval, offset and timezone weren't previously configurable,
        // so we can safely assume defaults (0 = midnight, UTC) for the "after" side if they're
        // not in the changes. We can't do this when switching between daily/weekly since those
        // fields may have been previously set to non-default values.
        const comingFromSubDay = isSubDayInterval(before.interval)
        const afterWithDefaults: ScheduleValues = comingFromSubDay
            ? { ...after, offset: after.offset ?? 0, timezone: after.timezone ?? 'UTC' }
            : after

        const beforeStr = formatSchedule(before.interval, before.offset, before.timezone)
        const afterStr = formatSchedule(
            afterWithDefaults.interval,
            afterWithDefaults.offset,
            afterWithDefaults.timezone
        )

        if (beforeStr && afterStr && beforeStr !== afterStr) {
            return [describeFieldChange('schedule', beforeStr, afterStr)]
        }
        if (afterStr) {
            return [describeFieldChange('schedule', null, afterStr)]
        }
        return [{ inline: <>updated the schedule for</>, inlist: <>updated schedule</> }]
    }

    // No interval change — describe each schedule field individually
    const descriptions: ChangeDescription[] = []

    if (before.timezone !== undefined || after.timezone !== undefined) {
        descriptions.push(describeFieldChange('schedule timezone', before.timezone ?? null, after.timezone ?? null))
    }
    if (before.offset !== undefined || after.offset !== undefined) {
        const beforeStr = before.offset !== undefined ? formatOffsetTime(before.offset) : null
        const afterStr = after.offset !== undefined ? formatOffsetTime(after.offset) : null
        descriptions.push(describeFieldChange('schedule start time', beforeStr, afterStr))
    }

    return descriptions
}

// ---------------------------------------------------------------------------
// Generic value formatting
// ---------------------------------------------------------------------------

/** Format a raw change value for display. Returns null if the value can't be meaningfully shown. */
function humanizeValue(value: unknown): string | null {
    if (value === null || value === undefined) {
        return null
    }
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false'
    }
    return JSON.stringify(value)
}

const FIELD_LABELS: Record<string, string> = {
    destination: 'destination config',
    start_at: 'start time',
    end_at: 'end time',
}

function humanizeFieldName(field: string): string {
    return FIELD_LABELS[field] ?? field.replace(/_/g, ' ')
}

// ---------------------------------------------------------------------------
// Change description builder
// ---------------------------------------------------------------------------

type ChangeDescription = { inline: string | JSX.Element; inlist: string | JSX.Element }

function describeFieldChange(label: string, before: string | null, after: string | null): ChangeDescription {
    if (before && after) {
        return {
            inline: (
                <>
                    changed the {label} from <strong>{before}</strong> to <strong>{after}</strong> for
                </>
            ),
            inlist: (
                <>
                    changed {label} from <strong>{before}</strong> to <strong>{after}</strong>
                </>
            ),
        }
    }
    if (after) {
        return {
            inline: (
                <>
                    changed the {label} to <strong>{after}</strong> for
                </>
            ),
            inlist: (
                <>
                    changed {label} to <strong>{after}</strong>
                </>
            ),
        }
    }
    return {
        inline: <>updated the {label} for</>,
        inlist: <>updated {label}</>,
    }
}

// ---------------------------------------------------------------------------
// Main describer
// ---------------------------------------------------------------------------

export function batchExportActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const name = userNameForLogItem(logItem)
    const exportName = nameOrLinkToBatchExport(logItem?.item_id, logItem?.detail.name)

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{name}</strong> created batch export {exportName}
                </>
            ),
        }
    }

    if (logItem.detail?.changes?.some((change) => change.field === 'deleted')) {
        const displayName = logItem.detail.name || '(unnamed export)'
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{name}</strong> deleted batch export{' '}
                    <strong>{displayName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes: ChangeDescription[] = []
        const scheduleChanges: ActivityChange[] = []

        for (const change of logItem.detail.changes ?? []) {
            if (change.field && SCHEDULE_FIELDS.has(change.field)) {
                scheduleChanges.push(change)
                continue
            }

            switch (change.field) {
                case 'enabled': {
                    // Raw value is "paused" — true means paused/disabled
                    if (change.after) {
                        changes.push({ inline: 'disabled', inlist: 'disabled the batch export' })
                    } else {
                        changes.push({ inline: 'enabled', inlist: 'enabled the batch export' })
                    }
                    break
                }
                case 'deleted': {
                    changes.push({ inline: 'deleted', inlist: 'deleted the batch export' })
                    break
                }
                default: {
                    changes.push(
                        describeFieldChange(
                            humanizeFieldName(change.field ?? ''),
                            humanizeValue(change.before),
                            humanizeValue(change.after)
                        )
                    )
                }
            }
        }

        changes.push(...describeScheduleChanges(scheduleChanges))

        if (changes.length === 0) {
            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{name}</strong> updated batch export {exportName}
                    </>
                ),
            }
        }

        return {
            description:
                changes.length === 1 ? (
                    <>
                        <strong className="ph-no-capture">{name}</strong> {changes[0].inline} batch export {exportName}
                    </>
                ) : (
                    <div>
                        <strong className="ph-no-capture">{name}</strong> updated batch export {exportName}
                        <ul className="ml-5 list-disc">
                            {changes.map((c, i) => (
                                <li key={i}>{c.inlist}</li>
                            ))}
                        </ul>
                    </div>
                ),
        }
    }

    return defaultDescriber(logItem, asNotification, exportName)
}
