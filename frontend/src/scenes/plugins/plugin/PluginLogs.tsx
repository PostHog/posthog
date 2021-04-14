import Table, { ColumnsType } from 'antd/lib/table'
import { kea, useValues } from 'kea'
import React from 'react'
import api from '../../../lib/api'
import { PluginLogEntryType } from '../../../types'
import { pluginLogsLogicType } from './PluginLogsType'

export interface PluginLogsProps {
    organizationId: string
    teamId: number
    pluginId: number
}

const pluginLogsLogic = kea<pluginLogsLogicType & { props: PluginLogsProps }>({
    key: ({ organizationId, teamId, pluginId }) => `${organizationId}-${teamId}-${pluginId}`,

    loaders: ({ props: { organizationId, teamId, pluginId }, values }) => ({
        pluginLogs: {
            __default: [] as PluginLogEntryType[],
            loadPluginLogsInitially: async () => {
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}`
                )
                return response.results
            },
            loadPluginLogsMore: async () => {
                const length = values.pluginLogs.length
                if (!length) {
                    return []
                }
                const before = values.pluginLogs[length - 1].timestamp
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}&before=${before}`
                )
                return [...values.pluginLogs, ...response.results]
            },
            loadPluginLogsPoll: async () => {
                if (!values.pluginLogs.length) {
                    return []
                }
                const after = values.pluginLogs[0].timestamp
                const response = await api.get(
                    `api/organizations/${organizationId}/plugins/${pluginId}/logs?team_id=${teamId}&after=${after}`
                )
                return [...response.results, ...values.pluginLogs]
            },
        },
    }),

    events: ({ actions, cache }) => ({
        afterMount: () => {
            actions.loadPluginLogsInitially()
            cache.pollingInterval = setInterval(actions.loadPluginLogsPoll, 2000)
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    }),
})

export function PluginLogs({ organizationId, teamId, pluginId }: PluginLogsProps): JSX.Element {
    const logic = pluginLogsLogic({ organizationId, teamId, pluginId })

    const { pluginLogs } = useValues(logic)

    const columns: ColumnsType<PluginLogEntryType> = [
        {
            title: 'Timestamp',
            dataIndex: 'timestamp',
            key: 'timestamp',
        },
        {
            title: 'Type',
            dataIndex: 'type',
            key: 'type',
        },
        {
            title: 'Message',
            dataIndex: 'message',
            key: 'message',
        },
    ]

    return (
        <Table
            dataSource={pluginLogs}
            columns={columns}
            rowKey="id"
            style={{ flexGrow: 1 }}
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
        />
    )
}
