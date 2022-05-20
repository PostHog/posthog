import { CaretRightOutlined, CaretDownOutlined, SyncOutlined, CloudDownloadOutlined } from '@ant-design/icons'
import { Button, Row } from 'antd'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { useActions, useValues } from 'kea'
import { PluginSection, pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { InstalledPlugin } from '../InstalledPlugin'
import { canInstallPlugins } from 'scenes/plugins/access'
import { userLogic } from 'scenes/userLogic'

export function UpgradeSection(): JSX.Element {
    const { checkForUpdates, toggleSectionOpen } = useActions(pluginsLogic)
    const { sectionsOpen } = useValues(pluginsLogic)
    const { user } = useValues(userLogic)

    const {
        filteredPluginsNeedingUpdates,
        pluginsNeedingUpdates,
        checkingForUpdates,
        installedPluginUrls,
        updateStatus,
        rearranging,
        hasUpdatablePlugins,
    } = useValues(pluginsLogic)

    const upgradeButton = canInstallPlugins(user?.organization) && hasUpdatablePlugins && (
        <Button
            type="default"
            icon={pluginsNeedingUpdates.length > 0 ? <SyncOutlined /> : <CloudDownloadOutlined />}
            onClick={(e) => {
                e.stopPropagation()
                checkForUpdates(true)
            }}
            loading={checkingForUpdates}
        >
            {checkingForUpdates
                ? `Checking app ${Object.keys(updateStatus).length + 1} out of ${
                      Object.keys(installedPluginUrls).length
                  }`
                : pluginsNeedingUpdates.length > 0
                ? 'Check again for updates'
                : 'Check for updates'}
        </Button>
    )

    return (
        <>
            <div
                className="plugins-installed-tab-section-header"
                onClick={() => toggleSectionOpen(PluginSection.Upgrade)}
            >
                <Subtitle
                    subtitle={
                        <>
                            {sectionsOpen.includes(PluginSection.Upgrade) ? (
                                <CaretDownOutlined />
                            ) : (
                                <CaretRightOutlined />
                            )}
                            {` Apps to update (${filteredPluginsNeedingUpdates.length})`}
                        </>
                    }
                    buttons={!rearranging && upgradeButton}
                />
            </div>
            {sectionsOpen.includes(PluginSection.Upgrade) ? (
                <>
                    {pluginsNeedingUpdates.length > 0 ? (
                        <Row gutter={16} style={{ marginTop: 16 }}>
                            {filteredPluginsNeedingUpdates.length > 0 ? (
                                <>
                                    {filteredPluginsNeedingUpdates.map((plugin) => (
                                        <InstalledPlugin key={plugin.id} plugin={plugin} showUpdateButton />
                                    ))}
                                </>
                            ) : (
                                <p style={{ margin: 10 }}>No apps match your search.</p>
                            )}
                        </Row>
                    ) : (
                        <p style={{ margin: 10 }}>All your apps are up to date. Great work!</p>
                    )}
                </>
            ) : null}
        </>
    )
}
