import React from 'react'
import { Button, Col, Row, Table, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { GithubOutlined, CheckOutlined, ToolOutlined, PauseOutlined } from '@ant-design/icons'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { userLogic } from 'scenes/userLogic'

function trimTag(tag: string): string {
    if (tag.match(/^[a-f0-9]{40}$/)) {
        return tag.substring(0, 7)
    }
    if (tag.length >= 20) {
        return tag.substring(0, 17) + '...'
    }
    return tag
}

export function InstalledPlugins(): JSX.Element {
    const { user } = useValues(userLogic)
    const { installedPlugins, loading } = useValues(pluginsLogic)
    const { editPlugin } = useActions(pluginsLogic)

    const canInstall = user?.plugin_access?.install

    return (
        <div>
            <h1 className="page-header">{canInstall ? 'Installed Plugins' : 'Plugins'}</h1>
            <Table
                data-attr="plugins-table"
                size="small"
                rowKey={(plugin) => plugin.name}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                dataSource={installedPlugins}
                columns={[
                    {
                        title: 'Plugin',
                        key: 'name',
                        render: function RenderPlugin(plugin: PluginTypeWithConfig): JSX.Element {
                            return (
                                <>
                                    <Row>
                                        <Col>
                                            <strong>{plugin.name}</strong>
                                        </Col>
                                    </Row>
                                    <Row gutter={16}>
                                        <Col>
                                            {plugin.pluginConfig?.enabled ? (
                                                <div style={{ color: 'var(--green)' }}>
                                                    <CheckOutlined />{' '}
                                                    {plugin.pluginConfig?.global ? 'Globally Enabled' : 'Enabled'}
                                                </div>
                                            ) : (
                                                <div style={{ color: 'var(--orange)' }}>
                                                    <PauseOutlined /> Disabled
                                                </div>
                                            )}
                                        </Col>
                                        <Col>
                                            {!plugin.url?.startsWith('file:') && (
                                                <a
                                                    href={`${plugin.url}/tree/${plugin.tag}`}
                                                    target="_blank"
                                                    rel="noreferrer noopener"
                                                >
                                                    <GithubOutlined /> {trimTag(plugin.tag)}
                                                </a>
                                            )}
                                        </Col>
                                    </Row>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Description',
                        key: 'description',
                        render: function RenderDescription(plugin: PluginTypeWithConfig): JSX.Element {
                            return <div>{plugin.description}</div>
                        },
                    },
                    {
                        title: '',
                        key: 'config',
                        align: 'right',
                        render: function RenderConfig(plugin: PluginTypeWithConfig): JSX.Element | null {
                            return !plugin.pluginConfig?.global ? (
                                <Tooltip title="Configure">
                                    <Button
                                        type="primary"
                                        icon={<ToolOutlined />}
                                        onClick={() => editPlugin(plugin.id)}
                                    />
                                </Tooltip>
                            ) : null
                        },
                    },
                ]}
                loading={loading}
                locale={{ emptyText: 'No Plugins Installed!' }}
            />
        </div>
    )
}
