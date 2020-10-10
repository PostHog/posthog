import React from 'react'
import { Button, Table, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginType } from '~/types'
import { DownloadOutlined } from '@ant-design/icons'
import { PluginRepositoryEntry } from 'scenes/plugins/types'

export function Repository(): JSX.Element {
    const { loading, repositoryLoading, uninstalledPlugins } = useValues(pluginsLogic)
    const { installPlugin } = useActions(pluginsLogic)

    return (
        <div>
            <h1 className="page-header">Plugin Repository</h1>
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
                                <Tooltip title="Install">
                                    <Button
                                        type="primary"
                                        onClick={() => installPlugin(plugin.url)}
                                        icon={<DownloadOutlined />}
                                    />
                                </Tooltip>
                            )
                        },
                    },
                ]}
                loading={loading || repositoryLoading}
                locale={{ emptyText: 'All Plugins Installed!' }}
            />
        </div>
    )
}
