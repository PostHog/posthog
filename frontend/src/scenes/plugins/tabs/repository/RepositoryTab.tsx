import React from 'react'
import { Col, Row } from 'antd'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import { Subtitle } from 'lib/components/PageHeader'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { PluginsSearch } from '../../PluginsSearch'

export function RepositoryTab(): JSX.Element {
    const { repositoryLoading, uninstalledPlugins, filteredUninstalledPlugins } = useValues(pluginsLogic)

    return (
        <div>
            <Subtitle subtitle="Plugin Repository" />
            <PluginsSearch />
            <Row gutter={16} style={{ marginTop: 16 }}>
                {(!repositoryLoading || filteredUninstalledPlugins.length > 0) && (
                    <>
                        {filteredUninstalledPlugins.map((plugin) => {
                            return (
                                <PluginCard
                                    key={plugin.url}
                                    plugin={{
                                        name: plugin.name,
                                        url: plugin.url,
                                        description: plugin.description,
                                    }}
                                    maintainer={plugin.maintainer}
                                />
                            )
                        })}
                        {uninstalledPlugins.length == 0 && (
                            <Col span={24}>
                                You have already installed all available plugins from the official repository!
                            </Col>
                        )}
                    </>
                )}
            </Row>
            {repositoryLoading && filteredUninstalledPlugins.length === 0 && (
                <Row gutter={16}>
                    <PluginLoading />
                </Row>
            )}
        </div>
    )
}
