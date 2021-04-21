import { Button, Row, Space } from 'antd'
import Search from 'antd/lib/input/Search'
import dayjs from 'dayjs'
import { useActions, useValues } from 'kea'
import React from 'react'
import { ResizableColumnType, ResizableTable } from '../../../lib/components/ResizableTable'
import { pluralize } from '../../../lib/utils'
import { PluginLogEntry, PluginLogEntryType } from '../../../types'
import { LOGS_PORTION_LIMIT, pluginLogsLogic, PluginLogsProps } from './pluginLogsLogic'

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
        title: 'Type',
        key: 'type',
        dataIndex: 'type',
        span: 1,
        render: PluginLogEntryTypeDisplay,
    } as ResizableColumnType<PluginLogEntry, PluginLogEntryType>,
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        span: 6,
    },
]

export function PluginLogs({ organizationId, teamId, pluginId }: PluginLogsProps): JSX.Element {
    const logic = pluginLogsLogic({ organizationId, teamId, pluginId })

    const { pluginLogs, pluginLogsLoading, pluginLogsBackground, isThereMoreToLoad } = useValues(logic)
    const { revealBackground, loadPluginLogsAnew, loadPluginLogsMore } = useActions(logic)

    return (
        <Space direction="vertical" style={{ flexGrow: 1 }} className="ph-no-capture">
            <Row>
                <Search
                    loading={pluginLogsLoading}
                    onSearch={(value) => loadPluginLogsAnew(value)}
                    placeholder="Search for messages containing…"
                    allowClear
                />
            </Row>
            <Row>
                <Button
                    onClick={revealBackground}
                    loading={pluginLogsLoading}
                    style={{ flexGrow: 1 }}
                    disabled={!pluginLogsBackground.length}
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
                pagination={false}
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
