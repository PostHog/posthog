import { convertHogToJS } from '@posthog/hogvm'

import { ACCESS_TOKEN_PLACEHOLDER } from '~/config/constants'
import { CyclotronInputType } from '~/schema/cyclotron'
import { Hub } from '~/types'

import {
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionType,
} from '../types'
import { execHog } from '../utils/hog-exec'
import { LiquidRenderer } from '../utils/liquid'
import { PushSubscriptionsManagerService } from './managers/push-subscriptions-manager.service'
import { RecipientTokensService } from './messaging/recipient-tokens.service'

export type HogInputsServiceHub = Pick<
    Hub,
    'integrationManager' | 'ENCRYPTION_SALT_KEYS' | 'SITE_URL' | 'postgres' | 'encryptedFields'
>

export const EXTEND_OBJECT_KEY = '$$_extend_object'

export class HogInputsService {
    private recipientTokensService: RecipientTokensService
    private pushSubscriptionsManager: PushSubscriptionsManagerService

    constructor(private hub: HogInputsServiceHub) {
        this.recipientTokensService = new RecipientTokensService(hub)
        this.pushSubscriptionsManager = new PushSubscriptionsManagerService(hub.postgres, hub.encryptedFields)
    }

    public async buildInputs(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals,
        additionalInputs?: Record<string, any>
    ): Promise<Record<string, any>> {
        // TODO: Load the values from the integrationManager

        const hasPushSubscriptionInputs = hogFunction.inputs_schema?.some(
            (schema) => schema.type === 'push_subscription_distinct_id'
        )

        const inputs: HogFunctionType['inputs'] = {
            // Include the inputs from the hog function
            ...hogFunction.inputs,
            ...hogFunction.encrypted_inputs,
            // Plus any additional inputs
            ...additionalInputs,
            // and decode any integration inputs
            ...(await this.loadIntegrationInputs(hogFunction)),
        }

        const newGlobals: HogFunctionInvocationGlobalsWithInputs = {
            ...globals,
            inputs: {},
        }

        // Resolve push subscription inputs after we have newGlobals for template resolution
        if (hasPushSubscriptionInputs) {
            const pushSubscriptionInputs = await this.loadPushSubscriptionInputs(hogFunction, newGlobals)

            // Update the input values with resolved tokens
            for (const [key, resolvedInput] of Object.entries(pushSubscriptionInputs)) {
                if (inputs[key]) {
                    inputs[key].value = resolvedInput.value
                } else {
                    inputs[key] = resolvedInput
                }
            }
        }

        const _formatInput = async (input: CyclotronInputType, key: string): Promise<any> => {
            const templating = input.templating ?? 'hog'

            if (templating === 'liquid') {
                return formatLiquidInput(input.value, newGlobals, key)
            }
            if (templating === 'hog' && input?.bytecode) {
                return await formatHogInput(input.bytecode, newGlobals, key)
            }

            return input.value
        }

        // Add unsubscribe url if we have an email input here
        const emailInputSchema = hogFunction.inputs_schema?.find((input) =>
            ['native_email', 'email'].includes(input.type)
        )
        const emailInput = hogFunction.inputs?.[emailInputSchema?.key ?? '']

        if (emailInputSchema && emailInput) {
            // If we have an email value then we template it out to get the email address
            const emailValue = await _formatInput(emailInput, emailInputSchema.key)
            if (emailValue?.to?.email) {
                newGlobals.unsubscribe_url = this.recipientTokensService.generatePreferencesUrl({
                    team_id: hogFunction.team_id,
                    identifier: emailValue.to.email,
                })
            }
        }

        newGlobals.push_subscriptions = []

        const orderedInputs = Object.entries(inputs ?? {}).sort(([_, input1], [__, input2]) => {
            return (input1?.order ?? -1) - (input2?.order ?? -1)
        })

        for (const [key, input] of orderedInputs) {
            if (!input) {
                continue
            }

            newGlobals.inputs[key] = await _formatInput(input, key)
        }

        return newGlobals.inputs
    }

    public async buildInputsWithGlobals(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals,
        additionalInputs?: Record<string, any>
    ): Promise<HogFunctionInvocationGlobalsWithInputs> {
        return {
            ...globals,
            inputs: await this.buildInputs(hogFunction, globals, additionalInputs),
        }
    }

    public async loadIntegrationInputs(
        hogFunction: HogFunctionType
    ): Promise<Record<string, { value: Record<string, any> | null }>> {
        const inputsToLoad: Record<string, number> = {}

        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.type === 'integration') {
                const input = hogFunction.inputs?.[schema.key]
                const value = input?.value?.integrationId ?? input?.value
                if (value && typeof value === 'number') {
                    inputsToLoad[schema.key] = value
                }
            }
        })

        if (Object.keys(inputsToLoad).length === 0) {
            return {}
        }

        const integrations = await this.hub.integrationManager.getMany(Object.values(inputsToLoad))
        const returnInputs: Record<string, { value: Record<string, any> | null }> = {}

        Object.entries(inputsToLoad).forEach(([key, value]) => {
            returnInputs[key] = {
                value: null,
            }

            const integration = integrations[value]
            // IMPORTANT: Check the team ID is correct
            if (integration && integration.team_id === hogFunction.team_id) {
                returnInputs[key] = {
                    value: {
                        ...integration.config,
                        ...integration.sensitive_config,
                        ...(integration.sensitive_config.access_token || integration.config.access_token
                            ? {
                                  access_token: ACCESS_TOKEN_PLACEHOLDER + integration.id,
                                  access_token_raw:
                                      integration.sensitive_config.access_token ?? integration.config.access_token,
                              }
                            : {}),
                    },
                }
            }
        })

        return returnInputs
    }

    public async loadPushSubscriptionInputs(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobalsWithInputs
    ): Promise<Record<string, { value: string | null }>> {
        const inputsToLoad: Record<string, { rawValue: string; schema: HogFunctionInputSchemaType }> = {}

        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.type === 'push_subscription_distinct_id') {
                const input = hogFunction.inputs?.[schema.key]
                const value = input?.value
                if (value && typeof value === 'string') {
                    inputsToLoad[schema.key] = { rawValue: value, schema }
                }
            }
        })

        if (Object.keys(inputsToLoad).length === 0) {
            return {}
        }

        const returnInputs: Record<string, { value: string | null }> = {}

        for (const [key, { rawValue, schema }] of Object.entries(inputsToLoad)) {
            returnInputs[key] = {
                value: null,
            }

            let resolvedValue = rawValue
            const input = hogFunction.inputs?.[key]
            const templating = schema.templating ?? 'hog'
            if (templating === 'liquid' || rawValue.includes('{{')) {
                resolvedValue = formatLiquidInput(rawValue, globals, key)
            } else if (templating === 'hog' && input?.bytecode) {
                resolvedValue = await formatHogInput(input.bytecode, globals, key)
            }

            if (!resolvedValue || typeof resolvedValue !== 'string') {
                continue
            }

            const distinctId = resolvedValue

            // Step 1: Look up subscription by distinct_id directly
            const subscriptions = await this.pushSubscriptionsManager.get({
                teamId: hogFunction.team_id,
                distinctId,
                platform: schema.platform,
            })

            let subscription = subscriptions.length > 0 ? subscriptions[0] : null

            // Step 2: If not found, try fallback to other distinct_ids for same person
            if (!subscription) {
                const relatedDistinctIds = await this.pushSubscriptionsManager.getDistinctIdsForSamePerson(
                    hogFunction.team_id,
                    distinctId
                )

                if (relatedDistinctIds.length > 0) {
                    subscription = await this.pushSubscriptionsManager.findSubscriptionByPersonDistinctIds(
                        hogFunction.team_id,
                        relatedDistinctIds,
                        schema.platform
                    )

                    // Step 3: If found, update subscription to use new distinct_id
                    if (subscription) {
                        await this.pushSubscriptionsManager.updateDistinctId(
                            hogFunction.team_id,
                            subscription.id,
                            distinctId
                        )
                        // Update the subscription object to reflect the new distinct_id
                        subscription = {
                            ...subscription,
                            distinct_id: distinctId,
                        }
                    }
                }
            }

            if (subscription && subscription.is_active && subscription.team_id === hogFunction.team_id) {
                returnInputs[key] = {
                    value: subscription.token,
                }
            }
        }

        // TODOdin: Handle missing subscription here or in the hog function run?
        return returnInputs
    }
}

export const formatHogInput = async (
    bytecode: any,
    globals: HogFunctionInvocationGlobalsWithInputs,
    key?: string
): Promise<any> => {
    // Similar to how we generate the bytecode by iterating over the values,
    // here we iterate over the object and replace the bytecode with the actual values
    // bytecode is indicated as an array beginning with ["_H"] (versions 1+) or ["_h"] (version 0)

    if (bytecode === null || bytecode === undefined) {
        return bytecode // Preserve null and undefined values
    }

    if (Array.isArray(bytecode) && (bytecode[0] === '_h' || bytecode[0] === '_H')) {
        const { execResult: result, error } = await execHog(bytecode, { globals })
        if (!result || error) {
            throw error ?? result?.error
        }
        if (!result?.finished) {
            // NOT ALLOWED
            throw new Error(`Could not execute bytecode for input field: ${key}`)
        }
        return convertHogToJS(result.result)
    }

    if (Array.isArray(bytecode)) {
        return await Promise.all(bytecode.map((item) => formatHogInput(item, globals, key)))
    } else if (typeof bytecode === 'object' && bytecode !== null) {
        let ret: Record<string, any> = {}

        if (bytecode[EXTEND_OBJECT_KEY]) {
            const res = await formatHogInput(bytecode[EXTEND_OBJECT_KEY], globals, key)
            if (res && typeof res === 'object') {
                ret = {
                    ...res,
                }
            }
        }

        await Promise.all(
            Object.entries(bytecode).map(async ([subkey, value]) => {
                if (subkey === EXTEND_OBJECT_KEY) {
                    return
                }
                ret[subkey] = await formatHogInput(value, globals, key ? `${key}.${subkey}` : subkey)
            })
        )

        return ret
    }

    return bytecode
}

export const formatLiquidInput = (
    value: unknown,
    globals: HogFunctionInvocationGlobalsWithInputs,
    key?: string
): any => {
    if (value === null || value === undefined) {
        return value
    }

    if (typeof value === 'string') {
        return LiquidRenderer.renderWithHogFunctionGlobals(value, globals)
    }

    if (Array.isArray(value)) {
        return value.map((item) => formatLiquidInput(item, globals, key))
    }

    if (typeof value === 'object' && value !== null) {
        return Object.fromEntries(
            Object.entries(value).map(([key2, value]) => [
                key2,
                formatLiquidInput(value, globals, key ? `${key}.${key2}` : key2),
            ])
        )
    }

    return value
}
