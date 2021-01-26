import React from 'react'
import { Button, Col, Row } from 'antd'
import { CloudDownloadOutlined, SyncOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Subtitle } from 'lib/components/PageHeader'
import { userLogic } from 'scenes/userLogic'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { InstalledPlugin } from 'scenes/plugins/tabs/installed/InstalledPlugin'

export function InstalledTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        installedPlugins,
        loading,
        checkingForUpdates,
        hasNonSourcePlugins,
        pluginsNeedingUpdates,
        installedPluginUrls,
        updateStatus,
    } = useValues(pluginsLogic)
    const { checkForUpdates } = useActions(pluginsLogic)

    const upgradeButton =
        user?.plugin_access.install && hasNonSourcePlugins ? (
            <Button
                type="primary"
                icon={pluginsNeedingUpdates.length > 0 ? <SyncOutlined /> : <CloudDownloadOutlined />}
                onClick={() => checkForUpdates(true)}
                loading={checkingForUpdates}
            >
                {checkingForUpdates
                    ? `Checking plugin ${Object.keys(updateStatus).length + 1} out of ${
                          Object.keys(installedPluginUrls).length
                      }`
                    : pluginsNeedingUpdates.length > 0
                    ? 'Check again'
                    : 'Check for updates'}
            </Button>
        ) : null

    return (
        <div>
            {pluginsNeedingUpdates.length > 0 ? (
                <>
                    <Subtitle
                        subtitle={`Plugins to update (${pluginsNeedingUpdates.length})`}
                        buttons={<>{upgradeButton}</>}
                    />
                    <Row gutter={16} style={{ marginTop: 16 }}>
                        {pluginsNeedingUpdates.map((plugin) => (
                            <InstalledPlugin key={plugin.id} plugin={plugin} showUpdateButton />
                        ))}
                    </Row>
                </>
            ) : null}

            <Subtitle
                subtitle={
                    'Installed Plugins' +
                    (!loading || installedPlugins.length > 0 ? ` (${installedPlugins.length})` : '')
                }
                buttons={<>{pluginsNeedingUpdates.length === 0 ? upgradeButton : null}</>}
            />
            <Row gutter={16} style={{ marginTop: 16 }}>
                {(!loading || installedPlugins.length > 0) && (
                    <>
                        {installedPlugins.map((plugin) => {
                            return <InstalledPlugin key={plugin.id} plugin={plugin} />
                        })}
                        {installedPlugins.length == 0 && <Col span={24}>You don't have any plugins installed yet.</Col>}
                    </>
                )}
                {loading && installedPlugins.length === 0 && <PluginLoading />}
            </Row>
        </div>
    )
}
