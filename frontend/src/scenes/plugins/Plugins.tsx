import './Plugins.scss'
import React, { useEffect } from 'react'
import { hot } from 'react-hot-loader/root'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { RepositoryTab } from 'scenes/plugins/tabs/repository/RepositoryTab'
import { InstalledTab } from 'scenes/plugins/tabs/installed/InstalledTab'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { pluginsLogic } from './pluginsLogic'
import { Alert, Tabs } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'
import { AdvancedTab } from 'scenes/plugins/tabs/advanced/AdvancedTab'
import posthog from 'posthog-js'

export const Plugins = hot(_Plugins)
function _Plugins(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    useEffect(() => {
        if (user && !user.plugin_access.configure) {
            window.location.href = '/'
        }
        posthog.persistence.register({ has_checked_out_plugins: true })
    }, [user])

    if (!user || !user.plugin_access.configure) {
        return null
    }

    return (
        <div className="plugins-scene">
            <PageHeader
                title="Plugins"
                caption="Plugins enable you to extend PostHog's core data processing functionality."
            />
            {!posthog.persistence.properties()['has_closed_plugins_end_of_beta'] && (
                <Alert
                    message="Beta Phase Completed"
                    description={
                        <>
                            Plugins are now a core feature of PostHog. Read more about this next step in our journey on
                            the PostHog blog.
                        </>
                    }
                    type="info"
                    showIcon
                    closable
                    onClose={() => posthog.persistence.register({ has_closed_plugins_end_of_beta: true })}
                    style={{ marginBottom: 32 }}
                />
            )}
            {user.plugin_access.install ? (
                <Tabs activeKey={pluginTab} onChange={(activeKey) => setPluginTab(activeKey as PluginTab)}>
                    <TabPane tab="Installed" key={PluginTab.Installed}>
                        <InstalledTab />
                    </TabPane>
                    <TabPane tab="Repository" key={PluginTab.Repository}>
                        <RepositoryTab />
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
