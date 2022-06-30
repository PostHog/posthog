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

    return null
}
