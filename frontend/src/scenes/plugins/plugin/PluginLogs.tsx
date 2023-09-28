import { Checkbox } from 'antd'
import { useActions, useValues } from 'kea'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { pluralize } from 'lib/utils'
import { PluginLogEntry, PluginLogEntryType } from '../../../types'
import { LOGS_PORTION_LIMIT, pluginLogsLogic, PluginLogsProps } from './pluginLogsLogic'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

function PluginLogEntryTypeDisplay(type: PluginLogEntryType): JSX.Element {
    let color: string | undefined
    switch (type) {
        case PluginLogEntryType.Debug:
            color = 'var(--muted)'
            break
        case PluginLogEntryType.Log:
            color = 'var(--default)'
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
        <div className="ph-no-capture space-y-2 flex-1">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
            />
            <div className="flex items-center gap-2">
                <span>Show logs of type:&nbsp;</span>
                <Checkbox.Group
                    options={Object.values(PluginLogEntryType)}
                    value={pluginLogsTypes}
                    onChange={setPluginLogsTypes}
                    style={{ marginLeft: '8px' }}
                />
            </div>
            <LemonButton
                onClick={revealBackground}
                loading={pluginLogsLoading}
                type="secondary"
                fullWidth
                center
                disabledReason={!pluginLogsBackground.length ? "There's nothing to load" : undefined}
            >
                {pluginLogsBackground.length
                    ? `Load ${pluralize(pluginLogsBackground.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>
            <ResizableTable
                dataSource={pluginLogs}
                columns={columns}
                loading={pluginLogsLoading}
                size="small"
                className="ph-no-capture"
                rowKey="id"
                style={{ flexGrow: 1, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!pluginLogs.length && (
                <LemonButton
                    onClick={loadPluginLogsMore}
                    loading={pluginLogsLoading}
                    type="secondary"
                    fullWidth
                    center
                    disabledReason={!isThereMoreToLoad ? "There's nothing mote to load" : undefined}
                >
                    {isThereMoreToLoad ? `Load up to ${LOGS_PORTION_LIMIT} older entries` : 'No older entries'}
                </LemonButton>
            )}
        </div>
    )
}
