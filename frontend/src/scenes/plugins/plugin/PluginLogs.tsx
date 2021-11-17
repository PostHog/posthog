import { Button, Checkbox, Row, Space } from 'antd'
import Search from 'antd/lib/input/Search'
import { LoadingOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import React from 'react'
import { ResizableColumnType, ResizableTable } from '../../../lib/components/ResizableTable'
import { pluralize } from '../../../lib/utils'
import { PluginLogEntry, PluginLogEntryType } from '../../../types'
import { LOGS_PORTION_LIMIT, pluginLogsLogic, PluginLogsProps } from './pluginLogsLogic'
import { dayjs } from 'lib/dayjs'

function PluginLogEntryTypeDisplay(type: PluginLogEntryType): JSX.Element {
    let color: string | undefined
    switch (type) {
        case PluginLogEntryType.Debug:
            color = 'var(--muted)'
            break
        case PluginLogEntryType.Log:
            color = 'var(--text-default)'
            break
        case PluginLogEntryType.Info:
            color = 'var(--blue)'
            break
        case PluginLogEntryType.Warn:
            color = 'var(--warning)'
            break
        case PluginLogEntryType.Error:
            color = 'var(--danger)'
            break
        default:
            break
    }
    return <span style={{ color }}>{type}</span>
}

const columns: ResizableColumnType<PluginLogEntry>[] = [
    {
        title: 'Timestamp',
        key: 'timestamp',
        dataIndex: 'timestamp',
        span: 3,
        render: (timestamp: string) => dayjs(timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
    },
    {
        title: 'Source',
        key: 'source',
        dataIndex: 'source',
        span: 1,
    } as ResizableColumnType<PluginLogEntry>,
    {
        title: 'Type',
        key: 'type',
        dataIndex: 'type',
        span: 1,
        render: PluginLogEntryTypeDisplay,
    } as ResizableColumnType<PluginLogEntry>,
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        span: 6,
    } as ResizableColumnType<PluginLogEntry>,
]

export function PluginLogs({ pluginConfigId }: PluginLogsProps): JSX.Element {
    const logic = pluginLogsLogic({ pluginConfigId })

    const { pluginLogs, pluginLogsLoading, pluginLogsBackground, isThereMoreToLoad, pluginLogsTypes } = useValues(logic)
    const { revealBackground, loadPluginLogsMore, setPluginLogsTypes, setSearchTerm } = useActions(logic)

    return (
        <Space direction="vertical" style={{ flexGrow: 1 }} className="ph-no-capture plugin-logs">
            <Row>
                <Search
                    loading={pluginLogsLoading}
                    onSearch={setSearchTerm}
                    placeholder="Search for messages containing…"
                    allowClear
                />
            </Row>
            <Row>
                <Space>
                    <span>Show logs of type:&nbsp;</span>
                    <Checkbox.Group
                        options={Object.values(PluginLogEntryType)}
                        value={pluginLogsTypes}
                        onChange={setPluginLogsTypes}
                        style={{ marginLeft: '8px' }}
                    />
                </Space>
            </Row>
            <Row>
                <Button
                    onClick={revealBackground}
                    loading={pluginLogsLoading}
                    style={{ flexGrow: 1 }}
                    disabled={!pluginLogsBackground.length}
                    icon={<LoadingOutlined />}
                >
                    {pluginLogsBackground.length
                        ? `Load ${pluralize(pluginLogsBackground.length, 'newer entry', 'newer entries')}`
                        : 'No new entries'}
                </Button>
            </Row>
            <ResizableTable
                dataSource={pluginLogs}
                columns={columns}
                loading={pluginLogsLoading}
                size="small"
                className="ph-no-capture"
                rowKey="id"
                style={{ flexGrow: 1 }}
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!pluginLogs.length && (
                <Row>
                    <Button
                        onClick={loadPluginLogsMore}
                        loading={pluginLogsLoading}
                        style={{ flexGrow: 1 }}
                        disabled={!isThereMoreToLoad}
                    >
                        {isThereMoreToLoad ? `Load up to ${LOGS_PORTION_LIMIT} older entries` : 'No older entries'}
                    </Button>
                </Row>
            )}
        </Space>
    )
}
