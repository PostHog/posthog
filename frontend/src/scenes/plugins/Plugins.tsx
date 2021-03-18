import './Plugins.scss'
import React, { useEffect } from 'react'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { RepositoryTab } from 'scenes/plugins/tabs/repository/RepositoryTab'
import { InstalledTab } from 'scenes/plugins/tabs/installed/InstalledTab'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { pluginsLogic } from './pluginsLogic'
import { Alert, Spin, Tabs, Tag } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'
import { AdvancedTab } from 'scenes/plugins/tabs/advanced/AdvancedTab'
import { canGloballyManagePlugins, canInstallPlugins, canViewPlugins } from './access'

export function Plugins(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    useEffect(() => {
        if (user) {
            if (!canViewPlugins(user.organization)) {
                window.location.href = '/'
                return
            }
            if (!user.flags.has_checked_out_plugins) {
                userUpdateRequest({ user: { flags: { has_checked_out_plugins: true } } })
                return
            }
        }
    }, [user])

    if (!user || !canViewPlugins(user.organization)) {
        return null
    }

    return (
        <div className="plugins-scene">
            <PageHeader
                title="Plugins"
                caption="Plugins enable you to extend PostHog's core data processing functionality."
            />
            {!user.flags['has_closed_plugins_end_of_beta'] && (
                <Alert
                    message="Out of Beta!"
                    description={
                        <>
                            Plugins are now a core feature of PostHog. Read more about this next step in our journey on
                            the PostHog blog.
                        </>
                    }
                    type="info"
                    showIcon
                    closable
                    onClose={() => {
                        if (!user.flags.has_closed_plugins_end_of_beta) {
                            userUpdateRequest({ user: { flags: { has_closed_plugins_end_of_beta: true } } })
                        }
                    }}
                    style={{ marginBottom: 32 }}
                />
            )}
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
                        <AdvancedTab user={user} />
                    </TabPane>
                </Tabs>
            ) : (
                <InstalledTab />
            )}
            <PluginDrawer />
        </div>
    )
}
