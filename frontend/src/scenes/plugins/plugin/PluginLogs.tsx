import { useActions, useValues } from 'kea'
import { pluralize } from 'lib/utils'
import { PluginLogEntryType } from '../../../types'
import { LOGS_PORTION_LIMIT, pluginLogsLogic, PluginLogsProps } from './pluginLogsLogic'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonCheckbox, LemonInput, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

function PluginLogEntryTypeDisplay(type: PluginLogEntryType): JSX.Element {
    let color: string | undefined
    switch (type) {
        case PluginLogEntryType.Debug:
            color = 'text-muted'
            break
        case PluginLogEntryType.Log:
            color = 'text-default'
            break
        case PluginLogEntryType.Info:
            color = 'text-primary'
            break
        case PluginLogEntryType.Warn:
            color = 'text-warning'
            break
        case PluginLogEntryType.Error:
            color = 'text-danger'
            break
        default:
            break
    }
    return <span className={color}>{type}</span>
}

const columns: LemonTableColumns<Record<string, any>> = [
    {
        title: 'Timestamp',
        key: 'timestamp',
        dataIndex: 'timestamp',
        render: (timestamp: string) => dayjs(timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
    },
    {
        title: 'Source',
        dataIndex: 'source',
        key: 'source',
    },
    {
        title: 'Type',
        key: 'type',
        dataIndex: 'type',
        render: PluginLogEntryTypeDisplay,
    },
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        render: (message: string) => <code className="whitespace-pre-wrap">{message}</code>,
    },
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
            <div className="flex items-center gap-4">
                <span>Show logs of type:&nbsp;</span>
                {Object.values(PluginLogEntryType).map((type) => {
                    return (
                        <LemonCheckbox
                            key={type}
                            label={type}
                            checked={pluginLogsTypes.includes(type)}
                            onChange={(checked) => {
                                const newPluginLogsTypes = checked
                                    ? [...pluginLogsTypes, type]
                                    : pluginLogsTypes.filter((t) => t != type)
                                setPluginLogsTypes(newPluginLogsTypes)
                            }}
                        />
                    )
                })}
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

            <LemonTable
                dataSource={pluginLogs}
                columns={columns}
                loading={pluginLogsLoading}
                size="small"
                className="ph-no-capture"
                rowKey="id"
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
