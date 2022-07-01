import { ActivityLogItem, ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import React from 'react'
import { SECRET_FIELD_VALUE } from './utils'

export function pluginActivityDescriber(logItem: ActivityLogItem): string | JSX.Element | null {
    if (logItem.scope !== ActivityScope.PLUGIN && logItem.scope !== ActivityScope.PLUGIN_CONFIG) {
        console.error('plugin describer received a non-plugin activity')
        return null
    }

    if (logItem.activity == 'installed') {
        return (
            <>
                installed the app: <b>{logItem.detail.name}</b>
            </>
        )
    }

    if (logItem.activity == 'uninstalled') {
        return (
            <>
                uninstalled the app: <b>{logItem.detail.name}</b>
            </>
        )
    }

    if (logItem.activity == 'enabled') {
        const changes: (string | JSX.Element)[] = []
        for (const change of logItem.detail.changes || []) {
            const newValue = change.after === SECRET_FIELD_VALUE ? '<secret_value>' : change.after
            changes.push(
                <>
                    field <code>{change.field}</code> set to <code>{newValue}</code>
                </>
            )
        }
        return (
            <SentenceList
                listParts={changes}
                prefix={
                    <>
                        enabled the app: <b>{logItem.detail.name}</b> with config ID {logItem.item_id}
                        {changes.length > 0 ? ', with' : '.'}
                    </>
                }
            />
        )
    }

    if (logItem.activity == 'disabled') {
        return (
            <>
                disabled the app: <b>{logItem.detail.name}</b> with config ID {logItem.item_id}.
            </>
        )
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
                        added new field <code>{change.field}</code>" with value <code>{changeAfter}</code>
                    </>
                )
            } else if (change.action === 'deleted') {
                changeWording = (
                    <>
                        removed field <code>{change.field}</code>, which had value <code>{changeBefore}</code>
                    </>
                )
            } else if (change.action === 'changed') {
                changeWording = (
                    <>
                        updated field <code>{change.field}</code> from value <code>{changeBefore}</code> to value{' '}
                        <code>{changeAfter}</code>{' '}
                    </>
                )
            }
            changes.push(changeWording)
        }
        return (
            <SentenceList
                listParts={changes}
                suffix={
                    <>
                        on app <b>{logItem.detail.name}</b> with config ID {logItem.item_id}.
                    </>
                }
            />
        )
    }

    return null
}
