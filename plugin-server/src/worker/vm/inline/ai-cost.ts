import { PluginEvent } from '@posthog/plugin-scaffold'
import { detect } from 'detect-browser'

import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType, PluginMethods } from '../../../types'
import { PluginInstance } from '../lazy'
import { costs as OpenAICosts } from './ai-cost-data/openai'
import { ModelRow } from './ai-cost-data/types'

export type UserAgentPluginConfiguration = {
    enable: string // unused
    enableSegmentAnalyticsJs?: string
    overrideUserAgentDetails?: string
    debugMode?: string
}

export class AICostPlugin implements PluginInstance {
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

    enableSegmentAnalyticsJs: boolean
    overrideUserAgentDetails: boolean
    debugMode: boolean

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.hub = hub
        this.config = pluginConfig
        this.usedImports = new Set()

        const config = pluginConfig.config as UserAgentPluginConfiguration

        this.enableSegmentAnalyticsJs = config.enableSegmentAnalyticsJs === 'true'
        this.overrideUserAgentDetails = config.overrideUserAgentDetails === 'true'
        this.debugMode = config.debugMode === 'true'

        this.methods = {
            processEvent: (event: PluginEvent) => {
                return this.addBrowserDetails(event)
            },
        }
    }

    public getPluginMethod<T extends keyof PluginMethods>(method_name: T): Promise<PluginMethods[T] | null> {
        return Promise.resolve(this.methods[method_name] as PluginMethods[T])
    }

    async addBrowserDetails(event: PluginEvent): Promise<PluginEvent> {
        if (event.event !== '$ai_generation') { 
            return event
        }

        if (!event.properties) {
            event.properties = {}
        }

        if (!event.properties['$ai_provider'] || !event.properties['$ai_model'] || !(event.properties['$ai_provider'] in PROVIDERS)) {
            return event
        }
        const cost = findCostFromModel(
            PROVIDERS[event.properties['$ai_provider'] as PROVIDER_NAMES],
            event.properties['$ai_model']
        )
        if(!cost) {
            return event
        }

        if(event.properties['$ai_input_tokens']) {
            event.properties['$ai_input_cost_usd'] = cost.cost.prompt_token * Number(event.properties['$ai_input_tokens'])
        }

        if(event.properties['$ai_output_tokens']) {
            event.properties['$ai_output_cost_usd'] = cost.cost.completion_token * Number(event.properties['$ai_output_cost_usd'])
        }

        return event
    }

    public async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        // TODO - this will be identical across all plugins, so figure out a better place to put it.
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.config,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }
}

const findCostFromModel = (costs: ModelRow[], aiModel: string): ModelRow | undefined => {
    return costs.find((cost) => {
        const valueLower = cost.model.value.toLowerCase();
        if (cost.model.operator === "equals") {
          return valueLower === aiModel;
        } else if (cost.model.operator === "startsWith") {
          return aiModel.startsWith(valueLower);
        } else if (cost.model.operator === "includes") {
          return aiModel.includes(valueLower);
        }
      });
}

enum PROVIDER_NAMES {
    OpenAI = "openai"
}

const PROVIDERS: Record<PROVIDER_NAMES, ModelRow[]> = {
    "openai": OpenAICosts
}