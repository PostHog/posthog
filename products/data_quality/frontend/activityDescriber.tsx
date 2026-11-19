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

import { ActivityScope } from '~/types'

import { checkTypeLabel } from './checksConstants'
import { DataQualityCheckSeverityEnumApi, DataQualityScheduleIntervalEnumApi } from './generated/api.schemas'

const INTERVAL_LABELS: Record<DataQualityScheduleIntervalEnumApi, string> = {
    [DataQualityScheduleIntervalEnumApi['1hour']]: 'every hour',
    [DataQualityScheduleIntervalEnumApi['6hour']]: 'every 6 hours',
    [DataQualityScheduleIntervalEnumApi['12hour']]: 'every 12 hours',
    [DataQualityScheduleIntervalEnumApi['24hour']]: 'daily',
    [DataQualityScheduleIntervalEnumApi['7day']]: 'weekly',
}

const SEVERITY_LABELS: Record<DataQualityCheckSeverityEnumApi, string> = {
    [DataQualityCheckSeverityEnumApi.Error]: 'error',
    [DataQualityCheckSeverityEnumApi.Warn]: 'warning',
}

// Written by the runner on every run, not by a person or agent editing the check.
const RUNNER_FIELDS = new Set(['failing_since', 'last_succeeded_at', 'updated_at'])

const intervalLabel = (value: ActivityChange['after']): string =>
    INTERVAL_LABELS[String(value) as DataQualityScheduleIntervalEnumApi] ?? String(value)

const severityLabel = (value: ActivityChange['after']): string =>
    SEVERITY_LABELS[String(value) as DataQualityCheckSeverityEnumApi] ?? String(value)

const changed = (field: string, change: ActivityChange, label: (value: string) => string = String): ChangeMapping => ({
    description: [
        <>
            changed the {field} from <strong>{change.before ? label(String(change.before)) : 'empty'}</strong> to{' '}
            <strong>{change.after ? label(String(change.after)) : 'empty'}</strong>
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
    check_type: (change) => changed('check type', change, checkTypeLabel),
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
    if (logItem.scope !== ActivityScope.DATA_QUALITY_CHECK) {
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
        // The runner also saves the check; an update that only touched its bookkeeping fields stays
        // out of the history. Any other field still gets an entry, even without a custom description.
        const changes = logItem.detail.changes ?? []
        if (changes.length > 0 && changes.every((change) => RUNNER_FIELDS.has(change.field ?? ''))) {
            return { description: null }
        }
        return (
            describeMappedChanges(logItem, CHECK_CHANGES, name, <>on the check {name}</>, asNotification) ??
            defaultDescriber(logItem, asNotification, name)
        )
    }

    return defaultDescriber(logItem, asNotification, name)
}

export function dataQualityCheckScheduleActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    if (logItem.scope !== ActivityScope.DATA_QUALITY_CHECK_SCHEDULE) {
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
