import React from 'react'
import { Col, Row } from 'antd'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginCard, PluginLoading } from './PluginCard'

export function Repository(): JSX.Element {
    const { loading, repositoryLoading, uninstalledPlugins } = useValues(pluginsLogic)

    return (
        <div>
            <h2 className="subtitle">Available</h2>
            <Row gutter={16}>
                {((!loading && !repositoryLoading) || uninstalledPlugins.length > 0) && (
                    <>
                        {uninstalledPlugins.map((plugin) => {
                            return (
                                <PluginCard
                                    key={plugin.url}
                                    name={plugin.name}
                                    url={plugin.url}
                                    description={plugin.description}
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
            {(loading || repositoryLoading) && uninstalledPlugins.length === 0 && <PluginLoading />}
        </div>
    )
}
