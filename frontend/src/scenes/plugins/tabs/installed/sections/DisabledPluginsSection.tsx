import { CaretRightOutlined, CaretDownOutlined } from '@ant-design/icons'
import { Row } from 'antd'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { useActions, useValues } from 'kea'
import { PluginSection, pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { InstalledPlugin } from '../InstalledPlugin'

export function DisabledPluginSection(): JSX.Element {
    const { filteredDisabledPlugins, sectionsOpen, disabledPlugins } = useValues(pluginsLogic)
    const { toggleSectionOpen } = useActions(pluginsLogic)

    if (disabledPlugins.length === 0) {
        return <></>
    }

    return (
        <>
            <div
                className="plugins-installed-tab-section-header"
                onClick={() => toggleSectionOpen(PluginSection.Disabled)}
            >
                <Subtitle
                    subtitle={
                        <>
                            {sectionsOpen.includes(PluginSection.Disabled) ? (
                                <CaretDownOutlined />
                            ) : (
                                <CaretRightOutlined />
                            )}
                            {` Installed apps (${filteredDisabledPlugins.length})`}
                        </>
                    }
                />
            </div>
            {sectionsOpen.includes(PluginSection.Disabled) ? (
                <>
                    {filteredDisabledPlugins.length > 0 ? (
                        <Row gutter={16} style={{ marginTop: 16 }}>
                            {filteredDisabledPlugins.map((plugin) => (
                                <InstalledPlugin key={plugin.id} plugin={plugin} />
                            ))}
                        </Row>
                    ) : (
                        <p style={{ margin: 10 }}>No apps match your search.</p>
                    )}
                </>
            ) : null}
        </>
    )
}
