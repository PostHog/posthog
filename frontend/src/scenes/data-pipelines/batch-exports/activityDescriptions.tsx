import {
    ActivityChange,
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToBatchExport = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(unnamed export)'
    return id ? <Link to={urls.batchExport(id)}>{displayName}</Link> : `${displayName}`
}

// ---------------------------------------------------------------------------
// Schedule display helpers
// ---------------------------------------------------------------------------

const SCHEDULE_FIELDS = new Set(['interval', 'interval_offset', 'timezone'])

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

function formatHour(hour: number): string {
    if (hour === 0) {
        return '12am'
    }
    if (hour < 12) {
        return `${hour}am`
    }
    if (hour === 12) {
        return '12pm'
    }
    return `${hour - 12}pm`
}

const asString = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined)
const asNumber = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined)

function isSubDayInterval(interval: string | undefined): boolean {
    return interval === 'hour' || (!!interval && interval.startsWith('every'))
}

/** Convert an offset in seconds to a readable time string. Null is treated as 0 (midnight). */
function offsetToTimeStr(offset: unknown): string | null {
    const seconds = typeof offset === 'number' ? offset : offset === null ? 0 : undefined
    if (seconds === undefined) {
        return null
    }
    return formatHour(Math.floor((seconds % 86400) / 3600))
}

/**
 * Build a human-readable schedule string from interval, offset, and timezone.
 * Examples: "hourly", "daily at 3am (Asia/Muscat)", "weekly on Monday at 1am (UTC)"
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
        const hourStr = formatHour(Math.floor((offset % 86400) / 3600))

        if (interval === 'week') {
            const dayName = day >= 0 && day < DAY_NAMES.length ? DAY_NAMES[day] : DAY_NAMES[0]
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
 * Collect schedule-related changes and produce descriptions.
 *
 * When the interval changes, we combine all schedule fields into one "schedule" description
 * (e.g. "changed schedule from hourly to daily at 3am (UTC)").
 *
 * When only timezone or start time changes (no interval change), we describe them individually
 * since we don't have enough context to build a full schedule string.
 */
function describeScheduleChanges(scheduleChanges: ActivityChange[]): ChangeDescription[] {
    if (scheduleChanges.length === 0) {
        return []
    }

    const changeByField = new Map(scheduleChanges.map((c) => [c.field, c]))
    const intervalChange = changeByField.get('interval')
    const offsetChange = changeByField.get('interval_offset')
    const timezoneChange = changeByField.get('timezone')

    // When the interval changes, combine everything into a single "schedule" description
    if (intervalChange) {
        // When coming from a sub-day interval, offset and timezone weren't previously configurable,
        // so we can safely assume defaults (0 = midnight, UTC) for the "after" side if they're
        // not in the changes. We can't do this when switching between daily/weekly since those
        // fields may have been previously set to non-default values.
        const comingFromSubDay = isSubDayInterval(asString(intervalChange.before))
        const defaultOffset = comingFromSubDay ? 0 : undefined
        const defaultTimezone = comingFromSubDay ? 'UTC' : undefined

        const beforeOffset = offsetChange ? asNumber(offsetChange.before) : undefined
        const afterOffset = offsetChange ? asNumber(offsetChange.after) : defaultOffset

        const beforeTimezone = timezoneChange ? asString(timezoneChange.before) : undefined
        const afterTimezone = timezoneChange ? asString(timezoneChange.after) : defaultTimezone

        const before = formatSchedule(asString(intervalChange.before), beforeOffset, beforeTimezone)
        const after = formatSchedule(asString(intervalChange.after), afterOffset, afterTimezone)

        if (before && after && before !== after) {
            return [describeFieldChange('schedule', before, after)]
        }
        if (after) {
            return [describeFieldChange('schedule', null, after)]
        }
        return [{ inline: <>updated the schedule for</>, inlist: <>updated schedule</> }]
    }

    // No interval change — describe each schedule field individually
    const descriptions: ChangeDescription[] = []

    if (timezoneChange) {
        const before = asString(timezoneChange.before) ?? null
        const after = asString(timezoneChange.after) ?? null
        descriptions.push(describeFieldChange('schedule timezone', before, after))
    }
    if (offsetChange) {
        descriptions.push(
            describeFieldChange(
                'schedule start time',
                offsetToTimeStr(offsetChange.before),
                offsetToTimeStr(offsetChange.after)
            )
        )
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
    name: 'name',
    model: 'model',
    filters: 'filters',
    destination: 'destination config',
    schema: 'schema',
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
