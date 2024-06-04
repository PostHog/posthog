import { exec, VMState } from '@posthog/hogvm'
import { Webhook } from '@posthog/plugin-scaffold'
import { PluginsServerConfig } from 'types'

import { trackedFetch } from '../../utils/fetch'
import { RustyHook } from '../rusty-hook'
import { HogFunctionManager } from './hog-function-manager'
import { HogFunctionInvocation, HogFunctionInvocationAsyncResponse, HogFunctionType } from './types'

export class HogExecutor {
    private rustyHook: RustyHook
    constructor(private serverConfig: PluginsServerConfig, private hogFunctionManager: HogFunctionManager) {
        this.rustyHook = new RustyHook(serverConfig)
    }

    /**
     * Intended to be invoked as a starting point from an event
     */
    async executeMatchingFunctions(invocation: HogFunctionInvocation): Promise<any> {
        const functions = this.hogFunctionManager.getTeamHogFunctions(invocation.context.project.id)

        if (!Object.keys(functions).length) {
            return
        }

        // TODO: Filter the functions based on the filters object
        for (const hogFunction of Object.values(functions)) {
            const fields = await this.buildHogFunctionFields(hogFunction, invocation)

            await this.execute(hogFunction, fields)
        }
    }

    /**
     * Intended to be invoked as a continuation from an async function
     */
    async executeAsyncResponse(invocation: HogFunctionInvocationAsyncResponse): Promise<any> {
        if (!invocation.hogFunctionId) {
            throw new Error('No hog function id provided')
        }

        const hogFunction = this.hogFunctionManager.getTeamHogFunctions(invocation.context.project.id)[
            invocation.hogFunctionId
        ]

        // TODO: Filter the functions based on the filters object
        const fields = await this.buildHogFunctionFields(hogFunction, invocation)
        invocation.state.stack.push(invocation.response)

        await this.execute(hogFunction, fields, invocation.state)
    }

    async execute(hogFunction: HogFunctionType, fields: Record<string, any>, state?: VMState): Promise<any> {
        const SPECIAL_CONFIG_ID = -3 // Hardcoded to mean Hog

        console.log('Executing hog function:', hogFunction.id, hogFunction.bytecode)

        try {
            const res = exec(
                hogFunction.bytecode,
                {
                    fields: fields,
                    timeout: 100, // TODO: what should this be
                    maxAsyncSteps: 10, // TODO: what should this be
                    asyncFunctions: {
                        // We need to pass these in but they don't actually do anything as it is a sync exec
                        fetch: async () => Promise.resolve(),
                    },
                },
                state
            )

            if (!res.finished) {
                try {
                    switch (res.asyncFunctionName) {
                        case 'fetch':
                            // TODO: validate the args
                            const [url, options] = res.asyncFunctionArgs ?? []

                            const webhook: Webhook = {
                                url,
                                method: options.method || 'POST',
                                headers: options.headers || {
                                    'Content-Type': 'application/json',
                                },
                                body:
                                    typeof options.body === 'string'
                                        ? options.body
                                        : JSON.stringify(options.body, undefined, 4),
                            }

                            console.log('Hog Exec Result:', JSON.stringify(res), webhook)

                            const success = await this.rustyHook.enqueueIfEnabledForTeam({
                                webhook: webhook,
                                teamId: hogFunction.team_id,
                                pluginId: SPECIAL_CONFIG_ID,
                                pluginConfigId: SPECIAL_CONFIG_ID,
                            })

                            // TODO: Temporary test code
                            if (!success) {
                                const fetchResponse = await trackedFetch(url, {
                                    method: webhook.method,
                                    body: webhook.body,
                                    headers: webhook.headers,
                                    timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
                                })

                                break
                            }
                        default:
                        // TODO: Log error somewhere
                    }
                } catch (err) {
                    console.error(`Error executing async function: ${res.asyncFunctionName}`, err)
                }
            }

            // Handle the fetch call
            console.log('Hog result:', res)
        } catch (error) {
            console.error('Error executing function:', error)
        }
    }

    async buildHogFunctionFields(
        hogFunction: HogFunctionType,
        invocation: HogFunctionInvocation
    ): Promise<Record<string, any>> {
        const inputs = Object.entries(hogFunction.inputs).reduce((acc, [key, value]) => {
            acc[key] = value.value
            return acc
        }, {} as Record<string, any>)
        return {
            // Add all the root level fields
            ...invocation.context,
            inputs,
        }
    }
}

// async function formatConfigTemplates(
//     team: Team,
//     hub: Hub,
//     pluginConfig: PluginConfig,
//     event: PostIngestionEvent
// ): Promise<Record<string, any>> {
//     const team = await hub.teamManager.fetchTeam(event.teamId)
//     if (!team) {
//         throw new Error('Team not found')
//     }

//     const schema = pluginConfig.plugin?.config_schema
//     if (!schema) {
//         // NOTE: This shouldn't be possible and is more about typings
//         return pluginConfig.config
//     }

//     const schemaObject: Record<string, PluginConfigSchema> = Array.isArray(schema)
//         ? Object.fromEntries(schema.map((field) => [field.key, field]))
//         : schema

//     const webhookFormatter = new MessageFormatter({
//         event,
//         team,
//         siteUrl: hub.SITE_URL || 'http://localhost:8000',
//         sourceName: pluginConfig.name || pluginConfig.plugin?.name || 'Unnamed plugin',
//         sourcePath: `/pipeline/destinations/${pluginConfig.id}`,
//     })

//     const templatedConfig = { ...pluginConfig.config }

//     Object.keys(templatedConfig).forEach((key) => {
//         // If the field is a json field then we template it as such
//         const { type, templating } = schemaObject[key] ?? {}
//         const template = templatedConfig[key]

//         if (type && templating) {
//             if (type === 'string' && typeof template === 'string') {
//                 templatedConfig[key] = webhookFormatter.format(template)
//             }

//             if (type === 'json' && typeof template === 'string') {
//                 try {
//                     templatedConfig[key] = JSON.stringify(webhookFormatter.formatJSON(JSON.parse(template)))
//                 } catch (error) {}
//             }

//             if (type === 'dictionary') {
//                 // TODO: Validate it really is a dictionary
//                 const dict: Record<string, string> = templatedConfig[key] as Record<string, string>
//                 const templatedDictionary: Record<string, string> = {}
//                 for (const [dictionaryKey, dictionaryValue] of Object.entries(dict)) {
//                     templatedDictionary[dictionaryKey] = webhookFormatter.format(dictionaryValue)
//                 }
//                 templatedConfig[key] = templatedDictionary
//             }
//         }
//     })

//     return templatedConfig
// }
