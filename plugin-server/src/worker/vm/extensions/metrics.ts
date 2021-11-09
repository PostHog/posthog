import equal from 'fast-deep-equal'

import { Hub, MetricMathOperations, PluginConfig, PluginMetricsVmResponse, StoredPluginMetrics } from '../../../types'
import { setPluginMetrics } from '../../../utils/db/sql'
import { IllegalOperationError } from '../../../utils/utils'

type MetricsOperations = {
    increment: (metricName: string, value: number) => Promise<void>
    max: (metricName: string, value: number) => Promise<void>
    min: (metricName: string, value: number) => Promise<void>
}
type Metrics = Record<string, Partial<MetricsOperations>>

export function createMetrics(hub: Hub, pluginConfig: PluginConfig): Metrics {
    return new Proxy(
        {},
        {
            get(_, key) {
                const availabeMetrics = pluginConfig.plugin?.metrics || {}

                if (typeof key !== 'string' || !Object.keys(availabeMetrics).includes(key)) {
                    throw new IllegalOperationError('Invalid metric name')
                }
                const defaultOptions = {
                    metricName: key,
                    pluginConfig,
                }

                if (availabeMetrics[key].toLowerCase() === 'sum') {
                    return {
                        increment: (value: number) => {
                            hub.pluginMetricsManager.updateMetric({
                                value,
                                metricOperation: MetricMathOperations.Increment,
                                ...defaultOptions,
                            })
                        },
                    }
                }

                if (availabeMetrics[key].toLowerCase() === 'max') {
                    return {
                        max: (value: number) => {
                            hub.pluginMetricsManager.updateMetric({
                                value,
                                metricOperation: MetricMathOperations.Max,
                                ...defaultOptions,
                            })
                        },
                    }
                }

                if (availabeMetrics[key].toLowerCase() === 'min') {
                    return {
                        min: (value: number) => {
                            hub.pluginMetricsManager.updateMetric({
                                value,
                                metricOperation: MetricMathOperations.Min,
                                ...defaultOptions,
                            })
                        },
                    }
                }

                return {}
            },
        }
    )
}

export function setupMetrics(
    hub: Hub,
    pluginConfig: PluginConfig,
    metrics: PluginMetricsVmResponse,
    exportEventsExists = false
): void {
    if (!pluginConfig.plugin) {
        return
    }

    let newMetrics: PluginMetricsVmResponse | StoredPluginMetrics = metrics
    const oldMetrics = pluginConfig.plugin.metrics

    if (!newMetrics) {
        // if exportEvents exists, we'll automatically assign metrics to it later
        if (!exportEventsExists) {
            // if there are old metrics set, we need to "erase" them
            // as this new version doesn't have any
            // if there are no metrics, no need for an update query
            if (oldMetrics && Object.keys(oldMetrics).length > 0) {
                void setPluginMetrics(hub, pluginConfig, {})
            }

            return
        }

        newMetrics = {}
    }

    for (const [metricName, metricType] of Object.entries(newMetrics)) {
        newMetrics[metricName] = metricType.toLowerCase()
    }

    const unsupportedMetrics = Object.values(newMetrics).filter((metric) => !['sum', 'max', 'min'].includes(metric))

    if (unsupportedMetrics.length > 0) {
        throw new IllegalOperationError(
            `Only 'sum', 'max', and 'min' are supported as metric types. Invalid types received: ${unsupportedMetrics.join(
                ', '
            )}`
        )
    }

    // add in the default exportEvents metrics
    if (exportEventsExists) {
        newMetrics = {
            ...newMetrics,
            events_seen: 'sum',
            events_delivered_successfully: 'sum',
            undelivered_events: 'sum',
            retry_errors: 'sum',
            other_errors: 'sum',
        }
    }

    if (!equal(oldMetrics, newMetrics)) {
        // validation above ensures newMetrics follows the StoredPluginMetrics type here
        void setPluginMetrics(hub, pluginConfig, newMetrics as StoredPluginMetrics)
        pluginConfig.plugin.metrics = newMetrics as StoredPluginMetrics
    }
}
