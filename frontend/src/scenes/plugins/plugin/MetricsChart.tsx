import React, { useEffect } from 'react'
import { useActions } from 'kea'
import { ActionsLineGraph } from 'scenes/trends/viz'
import './styles/metrics-drawer.scss'
import { PluginTypeWithConfig } from '../types'
import { FilterType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

const baseFilters = {
    insight: 'TRENDS',
    interval: 'day',
    display: 'ActionsLineGraph',
    filter_test_accounts: false,
    actions: [],
    new_entity: [],
    date_from: '-30d',
    refresh: true,
}

export function MetricsChart({ plugin }: { plugin: PluginTypeWithConfig }): JSX.Element {
    const eventFilters = Object.entries(plugin.metrics || {}).map(([metricName, math]) => {
        return {
            math: math as string,
            id: '$$plugin_metrics',
            name: '$$plugin_metrics',
            type: 'events',
            order: 0,
            math_property: metricName,
        }
    })

    const pluginNameFilter = { key: 'plugin_name', value: [plugin.name], operator: 'exact', type: 'event' }
    const pluginTagFilter = plugin.tag
        ? { key: 'plugin_tag', value: [plugin.tag], operator: 'exact', type: 'event' }
        : {}

    const filters = {
        ...baseFilters,
        events: eventFilters,
        properties: [pluginNameFilter, pluginTagFilter],
    } as Partial<FilterType>

    // TODO: verify this works fine
    const { loadResults } = useActions(insightLogic({ filters, dashboardItemId: null }))

    useEffect(() => {
        loadResults()
    }, [plugin])

    return (
        <div className="metrics-chart-wrapper">
            <ActionsLineGraph filters={filters} showPersonsModal={false} />
        </div>
    )
}
