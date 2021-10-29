import { IllegalOperationError } from '../utils/utils'
import { Hub, MetricMathOperations, PluginConfig, PluginConfigId } from './../types'
import { createPosthog } from './../worker/vm/extensions/posthog'

interface PluginMetrics {
    pluginConfig: PluginConfig
    metrics: Record<string, number>
}

interface UpdateMetricPayload {
    pluginConfig: PluginConfig
    metricOperation: MetricMathOperations
    metricName: string
    value: number
}

export class PluginMetricsManager {
    metricsPerPluginConfig: Record<PluginConfigId, PluginMetrics>

    constructor() {
        this.metricsPerPluginConfig = {}
    }

    async sendPluginMetrics(hub: Hub): Promise<void> {
        for (const pluginConfigMetrics of Object.values(this.metricsPerPluginConfig)) {
            const config = pluginConfigMetrics.pluginConfig
            const posthog = createPosthog(hub, config)
            await posthog.capture(`$$plugin_metrics`, {
                ...pluginConfigMetrics.metrics,
                plugin_name: config.plugin!.name,
                plugin_id: config.plugin!.id,
                plugin_tag: config.plugin!.tag,
            })
        }
        this.metricsPerPluginConfig = {}
    }

    setupMetricsObjectIfNeeded(pluginConfig: PluginConfig): void {
        if (!this.metricsPerPluginConfig[pluginConfig.id]) {
            this.metricsPerPluginConfig[pluginConfig.id] = {
                pluginConfig,
                metrics: {},
            } as PluginMetrics
        }
    }

    updateMetric({ metricOperation, pluginConfig, metricName, value }: UpdateMetricPayload): void {
        if (!pluginConfig.plugin) {
            return
        }
        if (typeof value !== 'number') {
            throw new IllegalOperationError('Only numbers are allowed for operations on metrics')
        }
        this.setupMetricsObjectIfNeeded(pluginConfig)
        const currentMetric = this.metricsPerPluginConfig[pluginConfig.id].metrics[metricName]
        if (!currentMetric) {
            this.metricsPerPluginConfig[pluginConfig.id].metrics[metricName] = value
            return
        }
        switch (metricOperation) {
            case MetricMathOperations.Increment:
                this.metricsPerPluginConfig[pluginConfig.id].metrics[metricName] += value
                break
            case MetricMathOperations.Max:
                this.metricsPerPluginConfig[pluginConfig.id].metrics[metricName] = Math.max(value, currentMetric)
                break
            case MetricMathOperations.Min:
                this.metricsPerPluginConfig[pluginConfig.id].metrics[metricName] = Math.min(value, currentMetric)
                break
            default:
                throw new Error('Unsupported metric math operation!')
        }
    }
}
