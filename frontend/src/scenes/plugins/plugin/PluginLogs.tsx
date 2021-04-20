import { Button } from 'antd'
import { kea, useActions, useValues } from 'kea'
import React from 'react'
import api from '../../../lib/api'
import { ResizableColumnType, ResizableTable } from '../../../lib/components/ResizableTable'
import { pluralize } from '../../../lib/utils'
import { PluginLogEntry, PluginLogEntryType } from '../../../types'
import { pluginLogsLogicType } from './PluginLogsType'

export interface PluginLogsProps {
    organizationId: string
    teamId: number
    pluginId: number
}

const pluginLogsLogic = kea<pluginLogsLogicType & { props: PluginLogsProps }>({
    key: ({ organizationId, teamId, pluginId }) => `${organizationId}-${teamId}-${pluginId}`,

    actions: {
        clearPluginLogsBackground: true,
    },

    loaders: ({ props: { organizationId, teamId, pluginId }, values, actions, cache }) => ({
        pluginLogs: {
            __default: [] as PluginLogEntry[],
            loadPluginLogsInitially: async () => {
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}`
                )
                cache.pollingInterval = setInterval(actions.loadPluginLogsBackgroundPoll, 2000)
                return response.results
            },
            loadPluginLogsMore: async () => {
                const length = values.pluginLogs.length
                const before = length ? '&before=' + values.pluginLogs[length - 1].timestamp : ''
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}${before}`
                )
                return [...values.pluginLogs, ...response.results]
            },
            revealBackground: () => {
                const newArray = [...values.pluginLogsBackground, ...values.pluginLogs]
                actions.clearPluginLogsBackground()
                return newArray
            },
        },
        pluginLogsBackground: {
            __default: [] as PluginLogEntry[],
            loadPluginLogsBackgroundPoll: async () => {
                const after = values.leadingEntry ? '&after=' + values.leadingEntry.timestamp : ''
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}${after}`
                )
                return [...response.results, ...values.pluginLogsBackground]
            },
        },
    }),

    reducers: {
        pluginLogsBackground: {
            clearPluginLogsBackground: () => [],
        },
    },

    selectors: ({ selectors }) => ({
        leadingEntry: [
            () => [selectors.pluginLogs, selectors.pluginLogsBackground],
            (pluginLogs: PluginLogEntry[], pluginLogsBackground: PluginLogEntry[]): PluginLogEntry | null => {
                if (pluginLogsBackground.length) {
                    return pluginLogsBackground[0]
                }
                if (pluginLogs.length) {
                    return pluginLogs[0]
                }
                return null
            },
        ],
    }),

    events: ({ actions, cache }) => ({
        afterMount: () => {
            actions.loadPluginLogsInitially()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    }),
})

function PluginLogEntryTypeDisplay(type: PluginLogEntryType): JSX.Element {
    let color: string | undefined
    switch (type) {
        case PluginLogEntryType.Debug:
            color = 'gray'
            break
        case PluginLogEntryType.Log:
            color = 'gray'
            break
        case PluginLogEntryType.Info:
            color = 'blue'
            break
        case PluginLogEntryType.Warn:
            color = 'orange'
            break
        case PluginLogEntryType.Error:
            color = 'red'
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
        span: 2,
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
        span: 9,
    },
]

export function PluginLogs({ organizationId, teamId, pluginId }: PluginLogsProps): JSX.Element {
    const logic = pluginLogsLogic({ organizationId, teamId, pluginId })

    const { pluginLogs, pluginLogsLoading, pluginLogsBackground } = useValues(logic)
    const { revealBackground } = useActions(logic)

    return (
        <>
            {pluginLogsBackground.length ? (
                <Button onClick={revealBackground} loading={pluginLogsLoading}>
                    Load {pluralize(pluginLogsBackground.length, 'newer entry', 'newer entries')}
                </Button>
            ) : null}
            <ResizableTable
                dataSource={pluginLogs}
                columns={columns}
                loading={pluginLogsLoading}
                size="small"
                className="ph-no-capture"
                rowKey="id"
                style={{ flexGrow: 1 }}
                pagination={{ hideOnSinglePage: true }}
            />
        </>
    )
}
