import React from 'react'
import { Row } from 'antd'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginCard, PluginLoading } from './PluginCard'

export function Repository(): JSX.Element {
    const { loading, repositoryLoading, uninstalledPlugins } = useValues(pluginsLogic)

    return (
        <div>
            <h2 className="subtitle">Available</h2>
            <Row gutter={16}>
                {!loading && !repositoryLoading && (
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
                        {uninstalledPlugins.length == 0 && <div>You have already installed all available plugins!</div>}
                    </>
                )}
            </Row>
            {loading && <PluginLoading />}
        </div>
    )
}
