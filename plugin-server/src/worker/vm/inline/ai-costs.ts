import { PluginEvent } from '@posthog/plugin-scaffold'
import bigDecimal from 'js-big-decimal'

import { Hub, ModelRow, PluginConfig, PluginLogEntrySource, PluginLogEntryType, PluginMethods } from '../../../types'
import { providers } from '../../../utils/ai-cost-data/mappings'
import { status } from '../../../utils/status'
import { PluginInstance } from '../lazy'

export type AiCostPluginConfiguration = {
    debugMode?: string
}

export class AiCostPlugin implements PluginInstance {
    initialize = async () => {}
    failInitialization = async () => {}
    clearRetryTimeoutIfExists = async () => {}
    getTeardown = () => {
        return Promise.resolve(null)
    }
    getTask = () => {
        return Promise.resolve(null)
    }
    getScheduledTasks = () => {
        return Promise.resolve({})
    }
    setupPluginIfNeeded = () => {
        return Promise.resolve(true)
    }
    usedImports: Set<string> | undefined
    methods: PluginMethods

    hub: Hub
    config: PluginConfig

    debugMode: boolean

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.hub = hub
        this.config = pluginConfig
        this.usedImports = new Set()

        const config = pluginConfig.config as AiCostPluginConfiguration

        this.debugMode = config.debugMode === 'true'

        this.methods = {
            processEvent: (event: PluginEvent) => {
                return this.processEvent(event)
            },
        }
    }

    public getPluginMethod<T extends keyof PluginMethods>(method_name: T): Promise<PluginMethods[T] | null> {
        return Promise.resolve(this.methods[method_name] as PluginMethods[T])
    }

    public async processEvent(event: PluginEvent): Promise<PluginEvent> {
        await this.createLogEntry(`AiCostPlugin.processEvent(): Event`, PluginLogEntryType.Warn)
        status.info('🔁', `AiCostPlugin.processEvent(): Event`)

        if (event.event !== '$ai_generation' || !event.properties) {
            return event
        }

        if (!event.properties['$ai_provider'] || !event.properties['$ai_model']) {
            return event
        }

        const provider = providers.find(
            (provider) => event?.properties?.$ai_provider === provider.provider.toLowerCase()
        )
        if (!provider || !provider.costs) {
            return event
        }

        const cost = this.findCostFromModel(provider.costs, event.properties['$ai_model'])
        if (!cost) {
            return event
        }

        if (event.properties['$ai_input_tokens']) {
            event.properties['$ai_input_cost_usd'] = parseFloat(
                bigDecimal.multiply(cost.cost.prompt_token, event.properties['$ai_input_tokens'])
            )
        }

        if (event.properties['$ai_output_tokens']) {
            event.properties['$ai_output_cost_usd'] = parseFloat(
                bigDecimal.multiply(cost.cost.completion_token, event.properties['$ai_output_tokens'])
            )
        }

        if (event.properties['$ai_input_cost_usd'] && event.properties['$ai_output_cost_usd']) {
            event.properties['$ai_total_cost_usd'] = parseFloat(
                bigDecimal.add(event.properties['$ai_input_cost_usd'], event.properties['$ai_output_cost_usd'])
            )
        }
        return event
    }

    private findCostFromModel(costs: ModelRow[], aiModel: string): ModelRow | undefined {
        return costs.find((cost) => {
            const valueLower = cost.model.value.toLowerCase()
            if (cost.model.operator === 'startsWith') {
                return aiModel.startsWith(valueLower)
            } else if (cost.model.operator === 'includes') {
                return aiModel.includes(valueLower)
            }
            return valueLower === aiModel
        })
    }

    public async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.config,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }
}

// Define the configuration schema for the AI Cost plugin
export const AI_COST_CONFIG_SCHEMA = [
    {
        markdown: 'AI Cost plugin calculates the cost of AI generations based on the provider and model used.',
    },
    {
        key: 'debugMode',
        name: 'Enable Debug Mode',
        type: 'choice' as const,
        hint: 'Enable debug mode to log processing details.',
        choices: ['false', 'true'],
        default: 'false',
        required: false,
    },
]
