import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { dayjs } from 'lib/dayjs'

import { ActivityScope } from '~/types'

import { SECRET_FIELD_VALUE } from './configUtils'

export function pluginActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.PLUGIN && logItem.scope !== ActivityScope.PLUGIN_CONFIG) {
        console.error('plugin describer received a non-plugin activity')
        return { description: null }
    }

    if (logItem.activity == 'installed') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> installed the app: <b>{logItem.detail.name}</b>
                </>
            ),
        }
    }

    if (logItem.activity == 'uninstalled') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> uninstalled the app: <b>{logItem.detail.name}</b>
                </>
            ),
        }
    }

    if (logItem.activity == 'enabled') {
        const changes: (string | JSX.Element)[] = []
        for (const change of logItem.detail.changes || []) {
            const newValue = change.after === SECRET_FIELD_VALUE ? '<secret_value>' : change.after
            changes.push(
                <>
                    field <code>{change.field}</code> set to <code>{newValue as string}</code>
                </>
            )
        }
        return {
            description: (
                <SentenceList
                    listParts={changes}
                    prefix={
                        <>
                            <strong>{userNameForLogItem(logItem)}</strong> enabled the app: <b>{logItem.detail.name}</b>{' '}
                            with config ID {logItem.item_id}
                            {changes.length > 0 ? ', with' : '.'}
                        </>
                    }
                />
            ),
        }
    }

    if (logItem.activity == 'disabled') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> disabled the app: <b>{logItem.detail.name}</b> with
                    config ID {logItem.item_id}.
                </>
            ),
        }
    }

    if (logItem.activity == 'job_triggered' && logItem.detail.trigger?.job_type == 'Export historical events V2') {
        const [startDate, endDate] = logItem.detail.trigger.payload.dateRange
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> started exporting historical events between{' '}
                    {startDate} and {endDate} (inclusive).
                </>
            ),
        }
    }

    if (logItem.activity == 'job_triggered' && logItem.detail.trigger) {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> triggered job:{' '}
                    <code>{logItem.detail.trigger.job_type}</code> with config ID {logItem.item_id}.
                </>
            ),
            extendedDescription: (
                <>
                    Payload: <code>{JSON.stringify(logItem.detail.trigger.payload, null, 2)}</code>
                </>
            ),
        }
    }

    if (logItem.activity == 'export_success' && logItem.detail.trigger) {
        const { dateFrom, dateTo } = logItem.detail.trigger.payload
        const startDate = dayjs(dateFrom).format('YYYY-MM-DD')
        // :TRICKY: Internally export date range is non-inclusive so transform it to be inclusive
        const endDate = dayjs(dateTo).subtract(1, 'day').format('YYYY-MM-DD')

        return {
            description: (
                <>
                    Finished exporting historical events between {startDate} and {endDate} (inclusive).
                </>
            ),
        }
    }

    if (logItem.activity == 'export_fail' && logItem.detail.trigger) {
        const { dateFrom, dateTo } = logItem.detail.trigger.payload
        const startDate = dayjs(dateFrom).format('YYYY-MM-DD')
        // :TRICKY: Internally export date range is non-inclusive so transform it to be inclusive
        const endDate = dayjs(dateTo).subtract(1, 'day').format('YYYY-MM-DD')

        return {
            description: (
                <>
                    Fatal error exporting historical events between {startDate} and {endDate} (inclusive). Check logs
                    for more details.
                </>
            ),
        }
    }

    if (logItem.activity == 'config_updated') {
        const changes: (string | JSX.Element)[] = []
        for (const change of logItem.detail.changes || []) {
            let changeWording: string | JSX.Element = ''
            const changeBefore = change.before === SECRET_FIELD_VALUE ? '<secret_value>' : change.before
            const changeAfter = change.after === SECRET_FIELD_VALUE ? '<secret_value>' : change.after
            if (change.action === 'created') {
                changeWording = (
                    <>
                        added new field <code>{change.field}</code>" with value <code>{changeAfter as string}</code>
                    </>
                )
            } else if (change.action === 'deleted') {
                changeWording = (
                    <>
                        removed field <code>{change.field}</code>, which had value <code>{changeBefore as string}</code>
                    </>
                )
            } else if (change.action === 'changed') {
                changeWording = (
                    <>
                        updated field <code>{change.field}</code> from value <code>{changeBefore as string}</code> to
                        value <code>{changeAfter as string}</code>{' '}
                    </>
                )
            }
            changes.push(changeWording)
        }
        return {
            description: (
                <SentenceList
                    prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                    listParts={changes}
                    suffix={
                        <>
                            on app <b>{logItem.detail.name}</b> with config ID {logItem.item_id}.
                        </>
                    }
                />
            ),
        }
    }

    if (logItem.activity.startsWith('attachment_')) {
        for (const change of logItem.detail.changes || []) {
            let changeWording: string | JSX.Element = ''

            if (logItem.activity === 'attachment_created') {
                changeWording = (
                    <>
                        attached a file <code>{change.after as string}</code>
                    </>
                )
            } else if (logItem.activity == 'attachment_updated') {
                if (change.after === change.before) {
                    changeWording = (
                        <>
                            updated attached file <code>{change.after as string}</code>
                        </>
                    )
                } else {
                    changeWording = (
                        <>
                            updated attached file from <code>{change.before as string}</code> to{' '}
                            <code>{change.after as string}</code>
                        </>
                    )
                }
            } else if (logItem.activity === 'attachment_deleted') {
                changeWording = (
                    <>
                        deleted attached file <code>{change.before as string}</code>
                    </>
                )
            }

            return {
                description: (
                    <>
                        <strong>{userNameForLogItem(logItem)}</strong> {changeWording} on app:{' '}
                        <b>{logItem.detail.name}</b> with config ID {logItem.item_id}
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification)
}
