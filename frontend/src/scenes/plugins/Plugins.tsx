import './Plugins.scss'
import React, { useEffect } from 'react'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { RepositoryTab } from 'scenes/plugins/tabs/repository/RepositoryTab'
import { InstalledTab } from 'scenes/plugins/tabs/installed/InstalledTab'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from './pluginsLogic'
import { Tag, Tabs } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'
import { AdvancedTab } from 'scenes/plugins/tabs/advanced/AdvancedTab'
import { canGloballyManagePlugins, canInstallPlugins, canViewPlugins } from './access'
import { UserType } from '../../types'

export function Plugins({ user }: { user: UserType }): JSX.Element | null {
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    useEffect(() => {
        if (!canViewPlugins(user.organization)) {
            window.location.href = '/'
        }
    }, [user])

    if (!canViewPlugins(user.organization)) {
        return null
    }

    return (
        <div className="plugins-scene">
            <PageHeader
                title={
                    <>
                        Plugins
                        <sup>
                            <Tag color="orange" style={{ marginLeft: 8 }}>
                                BETA
                            </Tag>
                        </sup>
                    </>
                }
                caption="Plugins enable you to extend PostHog's core data processing functionality."
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
