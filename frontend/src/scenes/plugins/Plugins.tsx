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
import { OptInPlugins } from 'scenes/plugins/OptInPlugins'
import { OptOutPlugins } from 'scenes/plugins/OptOutPlugins'

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
            {user.team.plugins_opt_in ? <OptOutPlugins /> : null}
            <h1 className="page-header">
                Plugins <span style={{ color: 'var(--red)' }}>BETA!</span>
            </h1>

            {user.team.plugins_opt_in ? (
                <>
                    <Tabs activeKey={pluginTab} onChange={(activeKey) => setPluginTab(activeKey)}>
                        <TabPane tab="Installed" key="installed">
                            <InstalledPlugins />
                        </TabPane>
                        {user.plugin_access?.install && (
                            <TabPane tab="Available" key="available">
                                <Repository />
                                <CustomPlugin />
                            </TabPane>
                        )}
                    </Tabs>
                    <PluginModal />
                </>
            ) : (
                <div style={{ maxWidth: 600, marginTop: 20 }}>
                    <OptInPlugins />
                </div>
            )}
        </div>
    )
}
