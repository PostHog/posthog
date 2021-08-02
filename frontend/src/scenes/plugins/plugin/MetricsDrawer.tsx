import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from '../pluginsLogic'
import { Drawer } from 'antd'
import './styles/metrics-drawer.scss'
import { MetricsChart } from './MetricsChart'

export function MetricsDrawer(): JSX.Element {
    const { showingMetricsPlugin } = useValues(pluginsLogic)
    const { hidePluginMetrics } = useActions(pluginsLogic)

    return (
        <Drawer
            visible={!!showingMetricsPlugin}
            onClose={hidePluginMetrics}
            width={'min(90vw, 80rem)'}
            title={`Plugin Metrics${!!showingMetricsPlugin ? `: ${showingMetricsPlugin.name}` : ''}`}
            placement="left"
            destroyOnClose
            className="metrics-drawer"
        >
            {!!showingMetricsPlugin ? <MetricsChart plugin={showingMetricsPlugin} /> : null}
        </Drawer>
    )
}
