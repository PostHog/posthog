import './Plugins.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'
import { ActivityScope } from '~/types'

import { canGloballyManagePlugins, canViewPlugins } from './access'
import { pluginsLogic } from './pluginsLogic'
import { AppsManagementTab } from './tabs/apps/AppsManagementTab'
import { AppsTab } from './tabs/apps/AppsTab'
import { BatchExportsTab } from './tabs/batch-exports/BatchExportsTab'
import { PluginTab } from './types'

export const scene: SceneExport = {
    component: AppsScene,
    logic: pluginsLogic,
}

export function AppsScene(): JSX.Element | null {
    const { user, hasAvailableFeature } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    const hasDataPipelines = hasAvailableFeature(AvailableFeature.DATA_PIPELINES)

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
                tabbedPage
                buttons={
                    hasDataPipelines && pluginTab === PluginTab.BatchExports ? (
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
                    {
                        key: PluginTab.BatchExports,
                        label: 'Batch Exports',
                        content: <BatchExportsTab />,
                    },
                    {
                        key: PluginTab.History,
                        label: 'History',
                        content: <ActivityLog scope={ActivityScope.PLUGIN} />,
                    },
                    canGloballyManagePlugins(user?.organization) && {
                        key: PluginTab.AppsManagement,
                        label: 'Manage apps',
                        content: <AppsManagementTab />,
                    },
                ]}
            />
        </>
    )
}
