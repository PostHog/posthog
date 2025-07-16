import { convertHogToJS } from '@posthog/hogvm'

import { Hub } from '~/types'

import { HogFunctionInvocationGlobals, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { execHog } from '../utils/hog-exec'
import { LiquidRenderer } from '../utils/liquid'

export const EXTEND_OBJECT_KEY = '$$_extend_object'

export class HogInputsService {
    constructor(private hub: Hub) {}

    public async buildInputs(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals,
        additionalInputs?: Record<string, any>
    ): Promise<Record<string, any>> {
        // TODO: Load the values from the integrationManager

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

        const orderedInputs = Object.entries(inputs ?? {}).sort(([_, input1], [__, input2]) => {
            return (input1?.order ?? -1) - (input2?.order ?? -1)
        })

        for (const [key, input] of orderedInputs) {
            if (!input) {
                continue
            }

            newGlobals.inputs[key] = input.value

            const templating = input.templating ?? 'hog'

            if (templating === 'liquid') {
                newGlobals.inputs[key] = formatLiquidInput(input.value, newGlobals, key)
            } else if (templating === 'hog' && input?.bytecode) {
                newGlobals.inputs[key] = await formatHogInput(input.bytecode, newGlobals, key)
            }
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

    private async loadIntegrationInputs(hogFunction: HogFunctionType): Promise<Record<string, any>> {
        const inputs: Record<
            string,
            {
                value: number | Record<string, any>
            }
        > = {}

        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.type === 'integration') {
                const input = hogFunction.inputs?.[schema.key]
                const value = input?.value?.integrationId ?? input?.value
                if (value && typeof value === 'number') {
                    inputs[schema.key] = { value }
                }
            }
        })

        if (Object.keys(inputs).length === 0) {
            return {}
        }

        const integrations = await this.hub.integrationManager.getMany(
            Object.values(inputs).map((x) => x.value.toString())
        )

        Object.entries(inputs).forEach(([key, value]) => {
            const integration = integrations[value.value.toString()]
            // IMPORTANT: Check the team ID is correct
            if (integration && integration.team_id === hogFunction.team_id) {
                inputs[key] = {
                    value: {
                        ...integration.config,
                        ...integration.sensitive_config,
                    },
                }
            }
        })

        return inputs
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

const formatLiquidInput = (value: unknown, globals: HogFunctionInvocationGlobalsWithInputs, key?: string): any => {
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
