import Chance from 'chance'

import { buildGlobalsWithInputs } from '~/cdp/services/hog-executor.service'
import { NativeDestinationExecutorService } from '~/cdp/services/native-destination-executor.service'
import {
    HogFunctionInputSchemaType,
    HogFunctionInputType,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
} from '~/cdp/types'
import { createInvocation } from '~/cdp/utils/invocation-utils'

import { compileHog } from '../compiler'
import { NativeTemplate } from '../types'
import { DeepPartialHogFunctionInvocationGlobals } from './test-helpers'

export class DestinationTester {
    private executor: NativeDestinationExecutorService
    private mockFetch = jest.fn()

    constructor(private template: NativeTemplate) {
        this.template = template
        this.executor = new NativeDestinationExecutorService({} as any)

        this.executor.fetch = this.mockFetch

        this.mockFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ status: 'OK' }),
            text: () => Promise.resolve(JSON.stringify({ status: 'OK' })),
            headers: { 'content-type': 'application/json' },
        })
    }

    private async compileObject(obj: any): Promise<any> {
        if (Array.isArray(obj)) {
            return Promise.all(obj.map((item) => this.compileObject(item)))
        } else if (typeof obj === 'object') {
            const res: Record<string, any> = {}
            for (const [key, value] of Object.entries(obj)) {
                res[key] = await this.compileObject(value)
            }
            return res
        } else if (typeof obj === 'string') {
            return await compileHog(`return f'${obj}'`)
        } else {
            return undefined
        }
    }

    private async compileInputs(_inputs: Record<string, any>): Promise<Record<string, HogFunctionInputType>> {
        const defaultInputs = this.template.inputs_schema.reduce((acc, input) => {
            if (typeof input.default !== 'undefined') {
                acc[input.key] = input.default
            }
            return acc
        }, {} as Record<string, HogFunctionInputType>)

        const allInputs = { ...defaultInputs, ..._inputs }

        // Don't compile inputs that don't suppport templating
        const compiledEntries = await Promise.all(
            Object.entries(allInputs).map(async ([key, value]) => {
                const schema = this.template.inputs_schema.find((input) => input.key === key)
                if (schema?.templating === false) {
                    return [key, value]
                }
                return [key, await this.compileObject(value)]
            })
        )

        return compiledEntries.reduce((acc, [key, value]) => {
            acc[key] = {
                value: allInputs[key],
                bytecode: value,
            }
            return acc
        }, {} as Record<string, HogFunctionInputType>)
    }

    createGlobals(globals: DeepPartialHogFunctionInvocationGlobals = {}): HogFunctionInvocationGlobalsWithInputs {
        return {
            ...globals,
            inputs: {},
            project: { id: 1, name: 'project-name', url: 'https://us.posthog.com/projects/1' },
            event: {
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $current_url: 'https://example.com', ...globals.event?.properties },
                timestamp: '2024-01-01T00:00:00Z',
                elements_chain: '',
                url: 'https://us.posthog.com/projects/1/events/1234',
                ...globals.event,
            },
            person: {
                id: 'person-id',
                name: 'person-name',
                properties: { email: 'example@posthog.com', ...globals.person?.properties },
                url: 'https://us.posthog.com/projects/1/persons/1234',
                ...globals.person,
            },
            source: {
                url: 'https://us.posthog.com/hog_functions/1234',
                name: 'hog-function-name',
                ...globals.source,
            },
        }
    }

    async invokeMapping(
        mapping_name: string,
        globals: HogFunctionInvocationGlobals,
        inputs: Record<string, any>,
        mapping_inputs: Record<string, any>
    ) {
        if (!this.template.mapping_templates) {
            throw new Error('No mapping templates found')
        }

        const compiledInputs = await this.compileInputs(inputs)

        const compiledMappingInputs = {
            ...this.template.mapping_templates.find((mapping) => mapping.name === mapping_name),
            inputs: mapping_inputs,
        }

        if (!compiledMappingInputs.inputs_schema) {
            throw new Error('No inputs schema found for mapping')
        }

        const processedInputs = await Promise.all(
            compiledMappingInputs.inputs_schema
                .filter((input) => typeof input.default !== 'undefined')
                .map(async (input) => {
                    const value = mapping_inputs?.[input.key] ?? input.default
                    return {
                        key: input.key,
                        value,
                        bytecode: await this.compileObject(value),
                    }
                })
        )

        const inputsObj = processedInputs.reduce((acc, item) => {
            acc[item.key] = {
                value: item.value,
                bytecode: item.bytecode,
            }
            return acc
        }, {} as Record<string, HogFunctionInputType>)

        compiledMappingInputs.inputs = inputsObj

        const globalsWithInputs = await buildGlobalsWithInputs(this.createGlobals(globals), {
            ...compiledInputs,
            ...compiledMappingInputs.inputs,
        })
        const invocation = createInvocation(globalsWithInputs, {
            ...this.template,
            template_id: this.template.id,
            hog: 'return event',
            bytecode: [],
            team_id: 1,
            enabled: true,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            deleted: false,
            inputs: compiledInputs,
            mappings: [compiledMappingInputs],
            is_addon_required: false,
        })

        return this.executor.execute(invocation)
    }
}

export const generateTestData = (
    seedName: string,
    input_schema: HogFunctionInputSchemaType[],
    required: boolean
): Record<string, any> => {
    const generateValue = (input: HogFunctionInputSchemaType): any => {
        const chance = new Chance(seedName)

        if (Array.isArray(input.choices)) {
            const choice = chance.pickone(input.choices)
            return choice.value
        }

        let val: any
        switch (input.type) {
            case 'boolean':
                val = chance.bool()
                break
            case 'number':
                val = chance.integer()
                break
            default:
                // covers string
                switch (input.format) {
                    case 'date': {
                        const d = chance.date()
                        val = [d.getFullYear(), d.getMonth() + 1, d.getDate()]
                            .map((v) => String(v).padStart(2, '0'))
                            .join('-')
                        break
                    }
                    case 'date-time':
                        val = chance.date().toISOString()
                        break
                    case 'email':
                        val = chance.email()
                        break
                    case 'hostname':
                        val = chance.domain()
                        break
                    case 'ipv4':
                        val = chance.ip()
                        break
                    case 'ipv6':
                        val = chance.ipv6()
                        break
                    case 'time': {
                        const d = chance.date()
                        val = [d.getHours(), d.getMinutes(), d.getSeconds()]
                            .map((v) => String(v).padStart(2, '0'))
                            .join(':')
                        break
                    }
                    case 'uri':
                        val = chance.url()
                        break
                    case 'uuid':
                        val = chance.guid()
                        break
                    default:
                        val = chance.string()
                        break
                }
                break
        }
        return val
    }

    const inputs = input_schema.reduce((acc, input) => {
        if (input.required || required === false) {
            acc[input.key] = input.default ?? generateValue(input)
        }
        return acc
    }, {} as Record<string, any>)

    return inputs
}
