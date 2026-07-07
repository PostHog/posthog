import { convertHogToJS } from '@posthog/hogvm'

import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { ACCESS_TOKEN_PLACEHOLDER } from '~/common/config/constants'

import { logger } from '../../utils/logger'
import { HogFunctionInvocationGlobals, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { EncryptedFields } from '../utils/encryption-utils'
import { execHog } from '../utils/hog-exec'
import { LiquidRenderer } from '../utils/liquid'
import { getDevicePushSubscriptionToken } from '../utils/push-subscription-utils'
import { IntegrationManagerService } from './managers/integration-manager.service'
import { RecipientTokensService } from './messaging/recipient-tokens.service'

export const EXTEND_OBJECT_KEY = '$$_extend_object'

export class HogInputsService {
    constructor(
        private integrationManager: IntegrationManagerService,
        private recipientTokensService: RecipientTokensService,
        private encryptedFields: EncryptedFields
    ) {}

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

        // Build a lookup of schema types for post-render coercion
        const schemaTypes: Record<string, string> = {}
        for (const schema of hogFunction.inputs_schema ?? []) {
            schemaTypes[schema.key] = schema.type
        }

        const orderedInputs = Object.entries(inputs ?? {}).sort(([_k1, input1], [_k2, input2]) => {
            return (input1?.order ?? -1) - (input2?.order ?? -1)
        })

        for (const [key, input] of orderedInputs) {
            if (!input) {
                continue
            }

            let inputsResult = await _formatInput(input, key)

            // Safety net: coerce string results to booleans for boolean schema fields.
            // Handles edge cases where Liquid templating returns strings for boolean fields.
            if (schemaTypes[key] === 'boolean' && typeof inputsResult === 'string') {
                const lower = inputsResult.trim().toLowerCase()
                inputsResult = lower === 'true' || lower === '1'
            }

            newGlobals.inputs[key] = inputsResult
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

    private resolvePushSubscriptionInputs(
        hogFunction: HogFunctionType,
        integrationInputs: Record<string, { value: Record<string, any> | null }>,
        newGlobals: HogFunctionInvocationGlobalsWithInputs
    ): Record<string, { value: string | null }> {
        const result: Record<string, { value: string | null }> = {}
        const personProperties = newGlobals.person?.properties

        const appIdentifier = getAppIdentifierForPush(integrationInputs)

        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.type !== 'push_subscription') {
                return
            }

            if (!appIdentifier) {
                logger.warn('🦔', '[HogInputsService] No push integration found for push subscription input', {
                    hogFunctionId: hogFunction.id,
                    hogFunctionName: hogFunction.name,
                    teamId: hogFunction.team_id,
                    inputKey: schema.key,
                })
                result[schema.key] = { value: null }
                return
            }

            const token = getDevicePushSubscriptionToken(personProperties, appIdentifier, this.encryptedFields)
            result[schema.key] = { value: token }
        })

        return result
    }

    public async loadIntegrationInputs(
        hogFunction: HogFunctionType,
        newGlobals?: HogFunctionInvocationGlobalsWithInputs
    ): Promise<Record<string, { value: Record<string, any> | null }>> {
        const inputsToLoad: Record<string, number> = {}

        const allSchemas = [
            ...(hogFunction.inputs_schema ?? []),
            ...(hogFunction.mappings?.flatMap((m) => m.inputs_schema ?? []) ?? []),
        ]
        const allInputs: Record<string, CyclotronInputType | null | undefined> = {
            ...hogFunction.inputs,
        }
        for (const mapping of hogFunction.mappings ?? []) {
            Object.assign(allInputs, mapping.inputs)
        }

        allSchemas.forEach((schema) => {
            if (schema.type === 'integration') {
                const input = allInputs[schema.key]
                const value = input?.value
                if (value && typeof value === 'number') {
                    inputsToLoad[schema.key] = value
                }
            }
        })

        if (Object.keys(inputsToLoad).length === 0) {
            return {}
        }

        const integrations = await this.integrationManager.getMany(Object.values(inputsToLoad))
        const returnInputs: Record<string, { value: Record<string, any> | null }> = {}

        Object.entries(inputsToLoad).forEach(([key, value]) => {
            returnInputs[key] = { value: null }
            const integration = integrations[value]
            // IMPORTANT: Check the team ID is correct
            if (integration && integration.team_id === hogFunction.team_id) {
                returnInputs[key] = {
                    value: {
                        $integration_id: integration.id,
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
            const pushSubscriptionInputs = this.resolvePushSubscriptionInputs(hogFunction, returnInputs, newGlobals)
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

/**
 * Finds the app identifier (project_id for Firebase, bundle_id for APNS) from resolved
 * integration inputs. Used to key the $device_push_subscription_<appIdentifier> person property.
 */
export function getAppIdentifierForPush(
    integrationInputs: Record<string, { value: Record<string, any> | null }>
): string | null {
    for (const input of Object.values(integrationInputs)) {
        const value = input?.value
        if (!value) {
            continue
        }
        const appId = value.project_id ?? value.bundle_id
        if (typeof appId === 'string' && appId) {
            return appId
        }
    }
    return null
}
