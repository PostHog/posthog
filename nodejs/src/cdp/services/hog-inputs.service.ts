import { convertHogToJS } from '@posthog/hogvm'

import { ACCESS_TOKEN_PLACEHOLDER } from '~/config/constants'
import { CyclotronInputType } from '~/schema/cyclotron'
import { Hub } from '~/types'
import { PostgresUse } from '~/utils/db/postgres'

import { HogFunctionInvocationGlobals, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { execHog } from '../utils/hog-exec'
import { LiquidRenderer } from '../utils/liquid'
import { PushSubscription, PushSubscriptionsManagerService } from './managers/push-subscriptions-manager.service'
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

        // Check if function has push subscription inputs (type='push_subscription' or integration_field='push_subscription')
        const hasPushSubscriptionInputs = hogFunction.inputs_schema?.some(
            (schema) => schema.type === 'push_subscription' || schema.integration_field === 'push_subscription'
        )

        const inputs: HogFunctionType['inputs'] = {
            // Include the inputs from the hog function
            ...hogFunction.inputs,
            ...hogFunction.encrypted_inputs,
            // Plus any additional inputs
            ...additionalInputs,
            // and decode any integration inputs
            ...(await this.loadIntegrationInputs(hogFunction)),
            // and resolve any push subscription inputs (only if function has push subscription inputs)
            ...(hasPushSubscriptionInputs ? await this.loadPushSubscriptionInputs(hogFunction) : {}),
        }

        const newGlobals: HogFunctionInvocationGlobalsWithInputs = {
            ...globals,
            inputs: {},
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

        // Only load push_subscriptions globals if function uses push subscriptions
        // Check if function has push subscription inputs (type='push_subscription') or integration fields
        const usesPushSubscriptions = hogFunction.inputs_schema?.some(
            (schema) => schema.type === 'push_subscription' || schema.integration_field === 'push_subscription'
        )

        if (usesPushSubscriptions && globals.event?.distinct_id) {
            const pushSubscriptions = await this.pushSubscriptionsManager.get({
                teamId: hogFunction.team_id,
                distinctId: globals.event.distinct_id,
            })

            const pushSubscriptionsWithUserIds = await this.writeMissingUserIdsToDB(
                pushSubscriptions,
                hogFunction.team_id,
                globals.event.distinct_id
            )

            const { toKeep, toDisable } = this.selectLatestSubscriptionsByUserAndToken(pushSubscriptionsWithUserIds)

            if (toDisable.length > 0) {
                await this.pushSubscriptionsManager.deactivateSubscriptionsByIds(
                    hogFunction.team_id,
                    toDisable,
                    'Disabled because user+device has a more recent token'
                )
            }

            newGlobals.push_subscriptions = toKeep.map((id: string) => ({ id }))
        } else {
            newGlobals.push_subscriptions = []
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
        // TODO: Load the values from the integrationManager

        // Check if function has push subscription inputs (type='push_subscription' or integration_field='push_subscription')
        const hasPushSubscriptionInputs = hogFunction.inputs_schema?.some(
            (schema) => schema.type === 'push_subscription' || schema.integration_field === 'push_subscription'
        )

        const inputs: HogFunctionType['inputs'] = {
            // Include the inputs from the hog function
            ...hogFunction.inputs,
            ...hogFunction.encrypted_inputs,
            // Plus any additional inputs
            ...additionalInputs,
            // and decode any integration inputs
            ...(await this.loadIntegrationInputs(hogFunction)),
            // and resolve any push subscription inputs (only if function has push subscription inputs)
            ...(hasPushSubscriptionInputs ? await this.loadPushSubscriptionInputs(hogFunction) : {}),
        }

        const newGlobals: HogFunctionInvocationGlobalsWithInputs = {
            ...globals,
            inputs: {},
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

        // Only load push_subscriptions globals if function uses push subscriptions
        // Check if function has push subscription inputs (type='push_subscription') or integration fields
        const usesPushSubscriptions = hogFunction.inputs_schema?.some(
            (schema) => schema.type === 'push_subscription' || schema.integration_field === 'push_subscription'
        )

        if (usesPushSubscriptions && globals.event?.distinct_id) {
            const pushSubscriptions = await this.pushSubscriptionsManager.get({
                teamId: hogFunction.team_id,
                distinctId: globals.event.distinct_id,
            })

            const pushSubscriptionsWithUserIds = await this.writeMissingUserIdsToDB(
                pushSubscriptions,
                hogFunction.team_id,
                globals.event.distinct_id
            )

            const { toKeep, toDisable } = this.selectLatestSubscriptionsByUserAndToken(pushSubscriptionsWithUserIds)

            if (toDisable.length > 0) {
                await this.pushSubscriptionsManager.deactivateSubscriptionsByIds(
                    hogFunction.team_id,
                    toDisable,
                    'Disabled because user+device has a more recent token'
                )
            }

            newGlobals.push_subscriptions = toKeep.map((id: string) => ({ id }))
        } else {
            newGlobals.push_subscriptions = []
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

        return newGlobals
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
        hogFunction: HogFunctionType
    ): Promise<Record<string, { value: string | null }>> {
        const inputsToLoad: Record<string, string> = {}

        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.type === 'push_subscription' || schema.integration_field === 'push_subscription') {
                const input = hogFunction.inputs?.[schema.key]
                const value = input?.value
                if (value && typeof value === 'string') {
                    inputsToLoad[schema.key] = value
                }
            }
        })

        if (Object.keys(inputsToLoad).length === 0) {
            return {}
        }

        // Batch fetch all subscriptions at once
        const subscriptionIds = Object.values(inputsToLoad)
        const subscriptions = await this.pushSubscriptionsManager.getManyById(hogFunction.team_id, subscriptionIds)

        const returnInputs: Record<string, { value: string | null }> = {}

        for (const [key, subscriptionId] of Object.entries(inputsToLoad)) {
            returnInputs[key] = {
                value: null,
            }

            const subscription = subscriptions[subscriptionId]
            if (subscription && subscription.is_active && subscription.team_id === hogFunction.team_id) {
                returnInputs[key] = {
                    value: subscription.token,
                }
            }
        }

        return returnInputs
    }

    private async writeMissingUserIdsToDB(
        subscriptions: PushSubscription[],
        teamId: number,
        distinctId: string
    ): Promise<PushSubscription[]> {
        const subscriptionsWithoutPersonId = subscriptions.filter((sub) => sub.person_id === null)

        if (subscriptionsWithoutPersonId.length === 0) {
            return [...subscriptions]
        }

        const personDistinctIdQuery = `SELECT person_id
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND distinct_id = $2
            LIMIT 1`
        const personDistinctIdResult = await this.hub.postgres.query<{ person_id: number }>(
            PostgresUse.PERSONS_READ,
            personDistinctIdQuery,
            [teamId, distinctId],
            'checkPersonDistinctIdForPushSubscriptions'
        )

        if (personDistinctIdResult.rows.length === 0) {
            return [...subscriptions]
        }

        const personIdToAssign = personDistinctIdResult.rows[0].person_id

        const updates = subscriptionsWithoutPersonId.map((sub) => ({
            subscriptionId: sub.id,
            personId: personIdToAssign,
        }))
        await this.pushSubscriptionsManager.updatePersonIds(teamId, updates)

        // Return new subscriptions array with updated person_ids
        return subscriptions.map((sub) => {
            if (sub.person_id === null && subscriptionsWithoutPersonId.some((s) => s.id === sub.id)) {
                return { ...sub, person_id: personIdToAssign }
            }
            return { ...sub }
        })
    }

    private selectLatestSubscriptionsByUserAndToken(subscriptions: PushSubscription[]): {
        toKeep: string[]
        toDisable: string[]
    } {
        const grouped = new Map<string, PushSubscription[]>()

        // Group subscriptions by person_id + token_hash
        for (const sub of subscriptions) {
            const key = `${sub.person_id ?? 'null'}:${sub.token_hash}`
            const existing = grouped.get(key) || []
            existing.push(sub)
            grouped.set(key, existing)
        }

        const toKeep: string[] = []
        const toDisable: string[] = []

        for (const [, subs] of grouped.entries()) {
            if (subs.length === 1) {
                toKeep.push(subs[0].id)
                continue
            }

            // Sort by updated_at (or created_at if updated_at is null), descending
            subs.sort((a, b) => {
                const aTime = a.updated_at || a.created_at
                const bTime = b.updated_at || b.created_at
                return new Date(bTime).getTime() - new Date(aTime).getTime()
            })

            // Keep the latest one, disable the rest
            toKeep.push(subs[0].id)
            for (let i = 1; i < subs.length; i++) {
                toDisable.push(subs[i].id)
            }
        }

        return { toKeep, toDisable }
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
