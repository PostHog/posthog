import { ActivityLogItem, ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import React from 'react'

export function pluginActivityDescriber(logItem: ActivityLogItem): string | JSX.Element | null {
    if (logItem.scope !== ActivityScope.PLUGIN) {
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

    if (logItem.activity == 'order_changed') {
        return (
            <>
                moved the app <b>{logItem.detail.name}</b> from position {logItem.detail.changes?.[0].before} to position {logItem.detail.changes?.[0].after}
            </>
        )
    }

    console.log(logItem.detail.changes)
    // if (logItem.activity == 'config_updated') {
    //     return (
    //         <>
    //             updated the config for <b>{logItem.detail.name}</b> from {logItem.detail.changes?.[0].before} to {logItem.detail.changes?.[0].after}
    //         </>
    //     )
    // }

    return null
}
