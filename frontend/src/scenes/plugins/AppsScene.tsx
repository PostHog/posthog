import { useEffect } from 'react'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { DestinationsTab } from './tabs/exports/DestinationsTab'
import { PluginTab } from './types'
import { LemonButton } from '@posthog/lemon-ui'
import { AppsTab } from './tabs/exports/AppsTab'
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
    const { featureFlags } = useValues(featureFlagLogic)

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

            {!!featureFlags[FEATURE_FLAGS.NEW_EXPORT_LAYOUT] ? 
            <>
                <PageHeader
                    title="Apps & Export Destinations"
                    tabbedPage
                    buttons={
                        pluginTab === PluginTab.Apps ? (
                            <LemonButton type="primary" to={urls.batchExportNew()}>
                                New destination
                            </LemonButton>
                        ) : undefined
                    }
                />
                <LemonTabs
                    data-attr="apps-tabs"
                    activeKey={pluginTab}
                    onChange={(newKey) => setPluginTab(newKey)}
                    tabs={[
                        { key: PluginTab.Destinations, label: 'Destinations', content: <DestinationsTab /> },
                        {
                            key: PluginTab.Apps,
                            label: 'Apps',
                            content: <AppsTab />,
                        },
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
            </> :
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
            </>}
        </>
    )
}
