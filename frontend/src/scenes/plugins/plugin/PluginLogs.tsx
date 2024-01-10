import { LemonButton, LemonCheckbox, LemonInput, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'

import { PipelineAppLogLevel, pluginLogsLogic, PluginLogsProps } from './pluginLogsLogic'

function LogLevelDisplay(type: PipelineAppLogLevel): JSX.Element {
    let color: string | undefined
    switch (type) {
        case PipelineAppLogLevel.Debug:
            color = 'text-muted'
            break
        case PipelineAppLogLevel.Log:
            color = 'text-default'
            break
        case PipelineAppLogLevel.Info:
            color = 'text-primary'
            break
        case PipelineAppLogLevel.Warning:
            color = 'text-warning'
            break
        case PipelineAppLogLevel.Error:
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
        title: 'Level',
        key: 'level',
        dataIndex: 'level',
        render: LogLevelDisplay,
    },
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        render: (message: string) => <code className="whitespace-pre-wrap">{message}</code>,
    },
]

export function PluginLogs({ id, kind }: PluginLogsProps): JSX.Element {
    const logic = pluginLogsLogic({ id, kind })

    const { pluginLogs, pluginLogsLoading, pluginLogsBackground, isThereMoreToLoad, selectedLogLevels } =
        useValues(logic)
    const { revealBackground, loadPluginLogsMore, setSelectedLogLevels, setSearchTerm } = useActions(logic)

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
                {Object.values(PipelineAppLogLevel).map((level) => {
                    return (
                        <LemonCheckbox
                            key={level}
                            label={level}
                            checked={selectedLogLevels.includes(level)}
                            onChange={(checked) => {
                                const newLogLevels = checked
                                    ? [...selectedLogLevels, level]
                                    : selectedLogLevels.filter((t) => t != level)
                                setSelectedLogLevels(newLogLevels)
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
                    disabledReason={!isThereMoreToLoad ? "There's nothing more to load" : undefined}
                >
                    {isThereMoreToLoad ? `Load up to ${LOGS_PORTION_LIMIT} older entries` : 'No older entries'}
                </LemonButton>
            )}
        </div>
    )
}
