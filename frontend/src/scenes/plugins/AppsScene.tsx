import { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from './pluginsLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { canGloballyManagePlugins, canViewPlugins } from './access'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { BatchExportsTab } from './tabs/batch-exports/BatchExportsTab'
import { AppsTab } from './tabs/apps/AppsTab'
import { PluginTab } from './types'
import { LemonButton } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

import './Plugins.scss'
import { AppsManagementTab } from './tabs/apps/AppsManagementTab'

export const scene: SceneExport = {
    component: AppsScene,
    logic: pluginsLogic,
}

export function AppsScene(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    useEffect(() => {
        if (!canViewPlugins(user?.organization)) {
            window.location.href = '/'
        }
    }, [user])

    if (!user || !canViewPlugins(user?.organization)) {
        return null
    }

    return (
        <>
            <PageHeader
                title="Apps & Exports"
                tabbedPage
                buttons={
                    pluginTab === PluginTab.BatchExports ? (
                        <LemonButton type="primary" to={urls.batchExportNew()}>
                            Create export workflow
                        </LemonButton>
                    ) : undefined
                }
            />
            <LemonTabs
                data-attr="apps-tabs"
                activeKey={pluginTab}
                onChange={(newKey) => setPluginTab(newKey)}
                tabs={[
                    { key: PluginTab.Apps, label: 'Apps', content: <AppsTab /> },
                    { key: PluginTab.BatchExports, label: 'Batch Exports', content: <BatchExportsTab /> },
                    {
                        key: PluginTab.History,
                        label: 'History',
                        content: <ActivityLog scope={ActivityScope.PLUGIN} />,
                    },
                    canGloballyManagePlugins(user?.organization) && {
                        key: PluginTab.AppsManagement,
                        label: 'Apps Management',
                        content: <AppsManagementTab />,
                    },
                ]}
            />
        </>
    )
}
