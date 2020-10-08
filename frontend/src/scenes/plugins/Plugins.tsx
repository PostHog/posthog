import React from 'react'
import { Button, Col, Row, Table } from 'antd'
import { hot } from 'react-hot-loader/root'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginType } from '~/types'
import { LinkOutlined, ToolOutlined } from '@ant-design/icons'
import { PluginRepositoryEntry } from 'scenes/plugins/types'

export const Plugins = hot(_Plugins)
function _Plugins(): JSX.Element {
    const { plugins, pluginsLoading, repositoryLoading, uninstalledPlugins } = useValues(pluginsLogic)
    const { installPlugin } = useActions(pluginsLogic)

    return (
        <div>
            <h1 className="page-header">Installed Plugins</h1>
            <Table
                data-attr="plugins-table"
                size="small"
                rowKey={(plugin) => plugin.name}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                dataSource={Object.values(plugins)}
                columns={[
                    {
                        title: 'Plugin',
                        key: 'name',
                        render: function RenderPlugin(plugin: PluginType): JSX.Element {
                            return (
                                <>
                                    <Row>
                                        <Col>
                                            <strong>{plugin.name}</strong>
                                        </Col>
                                    </Row>
                                    <Row gutter={16}>
                                        <Col>{plugin.enabled ? 'Enabled' : 'Disabled'}</Col>
                                        <Col>
                                            <a href={plugin.url} target="_blank" rel="noreferrer noopener">
                                                <LinkOutlined /> Visit Site
                                            </a>
                                        </Col>
                                    </Row>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Config',
                        key: 'config',
                        render: function RenderConfig(plugin: PluginType): JSX.Element {
                            return (
                                <div>
                                    {Object.keys(plugin.config).map((configKey) => (
                                        <Row key={configKey}>{configKey}</Row>
                                    ))}
                                </div>
                            )
                        },
                    },
                    {
                        title: '',
                        key: 'config',
                        align: 'right',
                        render: function RenderConfig(): JSX.Element {
                            return <Button type="primary" icon={<ToolOutlined />} />
                        },
                    },
                ]}
                loading={pluginsLoading}
            />

            <br />

            <h1 className="page-header">Plugins To Install</h1>
            <Table
                data-attr="plugins-table"
                size="small"
                rowKey={(plugin) => plugin.name}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                dataSource={uninstalledPlugins}
                columns={[
                    {
                        title: 'Plugin',
                        key: 'name',
                        render: function RenderPlugin(plugin: PluginType): JSX.Element {
                            return (
                                <a href={plugin.url} target="_blank" rel="noreferrer noopener">
                                    {plugin.name}
                                </a>
                            )
                        },
                    },
                    {
                        title: 'Description',
                        key: 'description',
                        render: function RenderDescription(plugin: PluginRepositoryEntry): JSX.Element {
                            return <div>{plugin.description}</div>
                        },
                    },
                    {
                        title: '',
                        key: 'install',
                        align: 'right',
                        render: function RenderInstall(plugin: PluginRepositoryEntry): JSX.Element {
                            return (
                                <Button type="primary" onClick={() => installPlugin(plugin)}>
                                    Install
                                </Button>
                            )
                        },
                    },
                ]}
                loading={pluginsLoading || repositoryLoading}
            />
        </div>
    )
}
