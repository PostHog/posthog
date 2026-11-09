import { describeMappedChanges } from 'lib/components/ActivityLog/activityDescriptions/describeMappedChanges'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

const INTERVAL_LABELS: Record<string, string> = {
    '1hour': 'every hour',
    '6hour': 'every 6 hours',
    '12hour': 'every 12 hours',
    '24hour': 'daily',
    '7day': 'weekly',
}

const SEVERITY_LABELS: Record<string, string> = {
    error: 'error',
    warn: 'warning',
}

const intervalLabel = (value: ActivityChange['after']): string => INTERVAL_LABELS[String(value)] ?? String(value)

const severityLabel = (value: ActivityChange['after']): string => SEVERITY_LABELS[String(value)] ?? String(value)

const changed = (field: string, change: ActivityChange): ChangeMapping => ({
    description: [
        <>
            changed the {field} from <strong>{String(change.before ?? 'empty')}</strong> to{' '}
            <strong>{String(change.after ?? 'empty')}</strong>
        </>,
    ],
    summary: [`Changed the ${field}`],
})

const simple = (text: string): ChangeMapping => ({ description: [text] })

const CHECK_CHANGES: Record<string, (change: ActivityChange) => ChangeMapping | null> = {
    name: (change) => ({
        description: [
            <>
                renamed it from <strong>{String(change.before || 'unnamed')}</strong> to{' '}
                <strong>{String(change.after || 'unnamed')}</strong>
            </>,
        ],
        summary: ['Renamed'],
    }),
    description: () => simple('changed the description'),
    severity: (change) => ({
        description: [
            <>
                changed the severity from <strong>{severityLabel(change.before)}</strong> to{' '}
                <strong>{severityLabel(change.after)}</strong>
            </>,
        ],
        summary: ['Changed the severity'],
    }),
    enabled: (change) => simple(change.after ? 'turned the check on' : 'turned the check off'),
    column_name: (change) => changed('column', change),
    config: () => simple('changed the configuration'),
    tags: () => simple('changed the tags'),
    owner: () => simple('changed the owner'),
}

const SCHEDULE_CHANGES: Record<string, (change: ActivityChange) => ChangeMapping | null> = {
    interval: (change) => ({
        description: [
            <>
                changed the run frequency from <strong>{intervalLabel(change.before)}</strong> to{' '}
                <strong>{intervalLabel(change.after)}</strong>
            </>,
        ],
        summary: ['Changed the run frequency'],
    }),
    enabled: (change) => simple(change.after ? 'turned the schedule on' : 'turned the schedule off'),
}

export function dataQualityCheckActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'DataQualityCheck') {
        console.error('data quality check describer received a different scope')
        return { description: null }
    }

    const name = logItem.detail.name ? <strong>{logItem.detail.name}</strong> : 'a data quality check'

    if (logItem.activity === 'created') {
        return {
            summary: activityLogSummary(logItem, 'Created the check', name),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created the check {name}
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        // The runner also saves the check, so an update with no user-editable field in it is
        // bookkeeping and stays out of the history.
        return (
            describeMappedChanges(logItem, CHECK_CHANGES, name, <>on the check {name}</>, asNotification) ?? {
                description: null,
            }
        )
    }

    return defaultDescriber(logItem, asNotification, name)
}

export function dataQualityCheckScheduleActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope !== 'DataQualityCheckSchedule') {
        console.error('data quality check schedule describer received a different scope')
        return { description: null }
    }

    const name = logItem.detail.name ? <strong>{logItem.detail.name}</strong> : 'a data quality check schedule'

    if (logItem.activity === 'updated') {
        return (
            describeMappedChanges(logItem, SCHEDULE_CHANGES, name, <>for {name}</>, asNotification) ?? {
                description: null,
            }
        )
    }

    return defaultDescriber(logItem, asNotification, name)
}
