import './Plugins.scss'
import React, { useEffect } from 'react'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { RepositoryTab } from 'scenes/plugins/tabs/repository/RepositoryTab'
import { InstalledTab } from 'scenes/plugins/tabs/installed/InstalledTab'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { pluginsLogic } from './pluginsLogic'
import { Spin, Tabs, Tag } from 'antd'
import { OptInPlugins } from 'scenes/plugins/optin/OptInPlugins'
import { PageHeader } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'
import { AdvancedTab } from 'scenes/plugins/tabs/advanced/AdvancedTab'
import { canGloballyManagePlugins, canInstallPlugins, canViewPlugins } from './access'

export function Plugins(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    if (!user) {
        return <Spin />
    }

    if (!canViewPlugins(user.organization)) {
        useEffect(() => {
            window.location.href = '/'
        }, [])
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
                caption={user.team?.plugins_opt_in ? "Plugins enable you to extend PostHog's core functionality." : ''}
            />

            {user.team?.plugins_opt_in ? (
                <>
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
                </>
            ) : (
                <div style={{ maxWidth: 600, marginTop: 20 }}>
                    <OptInPlugins />
                </div>
            )}
        </div>
    )
}
