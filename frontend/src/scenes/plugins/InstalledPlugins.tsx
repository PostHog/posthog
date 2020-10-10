import React from 'react'
import { Button, Col, Row, Table, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginType } from '~/types'
import { GithubOutlined, CheckOutlined, ToolOutlined, PauseOutlined } from '@ant-design/icons'

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
    const { plugins, loading } = useValues(pluginsLogic)
    const { editPlugin } = useActions(pluginsLogic)

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
                                        <Col>
                                            {plugin.enabled ? (
                                                <div style={{ color: 'var(--green)' }}>
                                                    <CheckOutlined /> Enabled
                                                </div>
                                            ) : (
                                                <div style={{ color: 'var(--orange)' }}>
                                                    <PauseOutlined /> Disabled
                                                </div>
                                            )}
                                        </Col>
                                        <Col>
                                            <a
                                                href={`${plugin.url}/tree/${plugin.tag}`}
                                                target="_blank"
                                                rel="noreferrer noopener"
                                            >
                                                <GithubOutlined /> {trimTag(plugin.tag)}
                                            </a>
                                        </Col>
                                    </Row>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Description',
                        key: 'description',
                        render: function RenderDescription(plugin: PluginType): JSX.Element {
                            return <div>{plugin.description}</div>
                        },
                    },
                    {
                        title: '',
                        key: 'config',
                        align: 'right',
                        render: function RenderConfig(plugin: PluginType): JSX.Element {
                            return (
                                <Tooltip title="Configure">
                                    <Button
                                        type="primary"
                                        icon={<ToolOutlined />}
                                        onClick={() => editPlugin(plugin.name)}
                                    />
                                </Tooltip>
                            )
                        },
                    },
                ]}
                loading={loading}
                locale={{ emptyText: 'No Plugins Installed!' }}
            />
        </div>
    )
}
