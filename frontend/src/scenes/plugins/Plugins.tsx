import './Plugins.scss'
import React, { useEffect } from 'react'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { RepositoryTab } from 'scenes/plugins/tabs/repository/RepositoryTab'
import { InstalledTab } from 'scenes/plugins/tabs/installed/InstalledTab'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from './pluginsLogic'
import { Tabs } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'
import { AdvancedTab } from 'scenes/plugins/tabs/advanced/AdvancedTab'
import { canGloballyManagePlugins, canInstallPlugins, canViewPlugins } from './access'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { pluginActivityDescriber } from './pluginActivityDescriptions'
import { LemonTag } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: Plugins,
    logic: pluginsLogic,
}

const BetaTag = (): JSX.Element => (
    <LemonTag type="warning" style={{ verticalAlign: '0.125em', marginLeft: 6 }}>
        BETA
    </LemonTag>
)

export function Plugins(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    useEffect(() => {
        if (!canViewPlugins(user?.organization)) {
            window.location.href = '/'
        }
    }, [user])

    if (!user || !canViewPlugins(user?.organization)) {
        return null
    }

    return (
        <div className="plugins-scene">
            <PageHeader
                title="Apps"
                caption={
                    <>
                        Apps enable you to extend PostHog's core data processing functionality.
                        <br />
                        Make use of verified apps from the{' '}
                        <a href="https://posthog.com/apps" target="_blank">
                            App Library
                        </a>{' '}
                        – or{' '}
                        <a href="https://posthog.com/docs/apps/build" target="_blank">
                            build your own
                        </a>
                        .
                    </>
                }
            />
            {canInstallPlugins(user.organization) ? (
                <Tabs activeKey={pluginTab} onChange={(activeKey) => setPluginTab(activeKey as PluginTab)}>
                    <TabPane tab="Installed" key={PluginTab.Installed}>
                        <InstalledTab />
                    </TabPane>
                    {canGloballyManagePlugins(user.organization) && (
                        <TabPane tab="Repository" key={PluginTab.Repository}>
                            <RepositoryTab />
                        </TabPane>
                    )}
                    <TabPane
                        tab={
                            <>
                                History <BetaTag />{' '}
                            </>
                        }
                        key={PluginTab.History}
                    >
                        <ActivityLog scope={ActivityScope.PLUGIN} describer={pluginActivityDescriber} />
                    </TabPane>
                    <TabPane tab="Advanced" key={PluginTab.Advanced}>
                        <AdvancedTab />
                    </TabPane>
                </Tabs>
            ) : (
                <InstalledTab />
            )}
            <PluginDrawer />
        </div>
    )
}
