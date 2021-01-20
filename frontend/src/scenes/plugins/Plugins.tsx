import './Plugins.scss'
import React, { useEffect } from 'react'
import { hot } from 'react-hot-loader/root'
import { PluginDrawer } from 'scenes/plugins/PluginDrawer'
import { Repository } from 'scenes/plugins/Repository'
import { InstalledPlugins } from 'scenes/plugins/InstalledPlugins'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { pluginsLogic } from './pluginsLogic'
import { Alert, Tabs, Tag } from 'antd'
import { OptInPlugins } from 'scenes/plugins/OptInPlugins'
import { OptOutPlugins } from 'scenes/plugins/OptOutPlugins'
import { CustomPlugin } from 'scenes/plugins/install/CustomPlugin'
import { LocalPlugin } from 'scenes/plugins/install/LocalPlugin'
import { SourcePlugin } from 'scenes/plugins/install/SourcePlugin'
import { PageHeader, Subtitle } from 'lib/components/PageHeader'
import { PluginTab } from 'scenes/plugins/types'

export const Plugins = hot(_Plugins)
function _Plugins(): JSX.Element {
    const { user } = useValues(userLogic)
    const { pluginTab } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { TabPane } = Tabs

    if (!user) {
        return <div />
    }

    if (!user.plugin_access.configure) {
        useEffect(() => {
            window.location.href = '/'
        }, [])
        return <div />
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
                buttons={user.team?.plugins_opt_in && <OptOutPlugins />}
            />

            {user.team?.plugins_opt_in ? (
                <>
                    <Tabs activeKey={pluginTab} onChange={(activeKey) => setPluginTab(activeKey as PluginTab)}>
                        <TabPane tab="Installed" key={PluginTab.Installed}>
                            <InstalledPlugins />
                        </TabPane>
                        {user.plugin_access.install && (
                            <>
                                <TabPane tab="Repository" key={PluginTab.Repository}>
                                    <Subtitle subtitle="Plugin Repository" />
                                    <Repository />
                                </TabPane>
                                <TabPane tab="Custom" key={PluginTab.Custom}>
                                    <Alert
                                        message="Advanced Features Ahead"
                                        description={
                                            <>
                                                Create and install your <b>own plugins</b> or plugins from{' '}
                                                <b>third-parties</b>. If you're looking for officially supported
                                                plugins, try the{' '}
                                                <a
                                                    href="#"
                                                    onClick={(e) => {
                                                        e.preventDefault()
                                                        setPluginTab(PluginTab.Repository)
                                                    }}
                                                >
                                                    Plugin Repository
                                                </a>
                                                .
                                            </>
                                        }
                                        type="warning"
                                        showIcon
                                        closable
                                    />
                                    <Subtitle subtitle="Custom Plugins" />
                                    <SourcePlugin />
                                    <CustomPlugin />
                                    <LocalPlugin />
                                </TabPane>
                            </>
                        )}
                    </Tabs>
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
