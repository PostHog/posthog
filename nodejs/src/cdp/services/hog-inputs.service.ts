import { convertHogToJS } from '@posthog/hogvm'

import { ACCESS_TOKEN_PLACEHOLDER } from '~/config/constants'
import { CyclotronInputType } from '~/schema/cyclotron'
import { Hub } from '~/types'

import { logger } from '../../utils/logger'
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
        const newGlobals: HogFunctionInvocationGlobalsWithInputs = {
            ...globals,
            inputs: {},
        }
        const inputs: HogFunctionType['inputs'] = {
            // Include the inputs from the hog function
            ...hogFunction.inputs,
            ...hogFunction.encrypted_inputs,
            // Plus any additional inputs
            ...additionalInputs,
            // and decode any integration inputs (and push subscription inputs when newGlobals provided)
            ...(await this.loadIntegrationInputs(hogFunction, newGlobals)),
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
                newGlobals.unsubscribe_url_one_click = this.recipientTokensService.generateOneClickUnsubscribeUrl({
                    team_id: hogFunction.team_id,
                    identifier: emailValue.to.email,
                })
            }
        }

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

    private async resolvePushSubscriptionInputs(
        hogFunction: HogFunctionType,
        integrationInputs: Record<string, { value: Record<string, any> | null }>,
        newGlobals: HogFunctionInvocationGlobalsWithInputs
    ): Promise<Record<string, { value: string | null }>> {
        const hasPushSubscriptionInputs = hogFunction.inputs_schema?.some(
            (schema) => schema.type === 'push_subscription'
        )
        if (!hasPushSubscriptionInputs) {
            return {}
        }

        const inputsToLoad: Record<string, { rawValue: string; schema: HogFunctionInputSchemaType }> = {}
        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.type === 'push_subscription') {
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

        const fcmProjectId = getFcmProjectIdForPush(integrationInputs)

        const pushSubscriptionPairs: Record<
            string,
            { distinctId: string; fcmProjectId: string; platform?: 'android' | 'ios' }
        > = {}
        for (const [key, { rawValue, schema }] of Object.entries(inputsToLoad)) {
            let resolvedValue: unknown = rawValue
            const input = hogFunction.inputs?.[key]
            const templating = schema.templating ?? 'hog'
            if (templating === 'liquid' || rawValue.includes('{{')) {
                resolvedValue = formatLiquidInput(rawValue, newGlobals, key)
            } else if (templating === 'hog' && input?.bytecode) {
                resolvedValue = await formatHogInput(input.bytecode, newGlobals, key)
            }
            if (!resolvedValue || typeof resolvedValue !== 'string') {
                logger.warn('🦔', '[HogInputsService] Push subscription distinct_id template returned non-string', {
                    hogFunctionId: hogFunction.id,
                    hogFunctionName: hogFunction.name,
                    teamId: hogFunction.team_id,
                    inputKey: key,
                    resolvedValueType: typeof resolvedValue,
                })
                continue
            }
            pushSubscriptionPairs[key] = {
                distinctId: resolvedValue,
                fcmProjectId,
                platform: schema.platform,
            }
        }

        return await this.pushSubscriptionsManager.loadPushSubscriptions(hogFunction, pushSubscriptionPairs)
    }

    public async loadIntegrationInputs(
        hogFunction: HogFunctionType,
        newGlobals?: HogFunctionInvocationGlobalsWithInputs
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
            returnInputs[key] = { value: null }
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

        if (newGlobals) {
            const pushSubscriptionInputs = await this.resolvePushSubscriptionInputs(
                hogFunction,
                returnInputs,
                newGlobals
            )
            Object.assign(returnInputs, pushSubscriptionInputs)
        }

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

export function getFcmProjectIdForPush(
    integrationInputs: Record<string, { value: Record<string, any> | null }>
): string {
    const firebaseAccountInput = integrationInputs['firebase_account']
    if (!firebaseAccountInput?.value) {
        throw new Error(
            `firebase_account integration is required for push subscription inputs but was not found. ` +
                `Please configure the firebase_account integration in your hog function.`
        )
    }
    const fcmProjectId = (firebaseAccountInput.value as { key_info?: { project_id?: string } })?.key_info?.project_id
    if (!fcmProjectId) {
        throw new Error(
            `FCM project ID (project_id) not found in firebase_account integration. ` +
                `Please ensure the Firebase service account key contains a valid project_id.`
        )
    }
    return fcmProjectId
}
