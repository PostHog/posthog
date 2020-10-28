import React, { useEffect } from 'react'
import { hot } from 'react-hot-loader/root'
import { PluginModal } from 'scenes/plugins/PluginModal'
import { CustomPlugin } from 'scenes/plugins/CustomPlugin'
import { Repository } from 'scenes/plugins/Repository'
import { InstalledPlugins } from 'scenes/plugins/InstalledPlugins'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { pluginsLogic } from './pluginsLogic'
import { Tabs } from 'antd'

export const Plugins = hot(_Plugins)
function _Plugins(): JSX.Element {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    if (!user) {
        return <div />
    }

    if (!user?.plugin_access?.configure) {
        useEffect(() => {
            window.location.href = '/'
        }, [])
        return <div />
    }

    return (
        <div>
            <h1 className="oh-page-title">Plugins</h1>
            <div className="oh-page-caption">
                Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et
                dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation.
            </div>

            <Tabs activeKey={pluginTab} onChange={(activeKey) => setPluginTab(activeKey)}>
                <TabPane tab="Installed" key="installed">
                    <h2 className="oh-page-subtitle">Installed</h2>
                    <InstalledPlugins />
                </TabPane>
                {user.plugin_access?.install && (
                    <TabPane tab="Available" key="available">
                        <h2 className="oh-page-subtitle">Available</h2>
                        <Repository />
                        <CustomPlugin />
                    </TabPane>
                )}
            </Tabs>
            <PluginModal />
        </div>
    )
}
