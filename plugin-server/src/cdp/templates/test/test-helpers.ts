import Chance from 'chance'
import merge from 'deepmerge'
import { Settings } from 'luxon'

import { getTransformationFunctions } from '~/cdp/hog-transformations/transformation-functions'
import { formatLiquidInput } from '~/cdp/services/hog-inputs.service'
import { NativeDestinationExecutorService } from '~/cdp/services/native-destination-executor.service'
import { isNativeHogFunction } from '~/cdp/utils'
import { defaultConfig } from '~/config/config'
import { CyclotronInputType } from '~/schema/cyclotron'
import { GeoIPService, GeoIp } from '~/utils/geoip'

import { Hub } from '../../../types'
import { HogExecutorService } from '../../services/hog-executor.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionTemplate,
    HogFunctionTemplateCompiled,
    HogFunctionType,
    MinimalLogEntry,
    NativeTemplate,
} from '../../types'
import { cloneInvocation, createInvocation } from '../../utils/invocation-utils'
import { compileHog } from '../compiler'

/**
 * Sets templating value of 'hog' or 'liquid' on hog inputs based on the template used.
 */
export function propagateTemplatingFromSchema(template: any, input: any): any {
    const templatedInputs = { ...input }

    for (const field of template.inputs_schema) {
        if ('templating' in field) {
            const templating_val = field['templating']
            if (typeof templating_val === 'boolean') {
                if (templating_val) {
                    if (!templatedInputs[field.key] || typeof templatedInputs[field.key] !== 'object') {
                        templatedInputs[field.key] = { value: templatedInputs[field.key] }
                    }
                    templatedInputs[field.key]['templating'] = 'hog'
                }
                // If False, do not set templating field
            } else {
                if (!templatedInputs[field.key] || typeof templatedInputs[field.key] !== 'object') {
                    templatedInputs[field.key] = { value: templatedInputs[field.key] }
                }
                templatedInputs[field.key]['templating'] = templating_val
            }
        }
    }

    return templatedInputs
}

export type DeepPartialHogFunctionInvocationGlobals = {
    event?: Partial<HogFunctionInvocationGlobals['event']>
    person?: Partial<HogFunctionInvocationGlobals['person']>
    source?: Partial<HogFunctionInvocationGlobals['source']>
    request?: HogFunctionInvocationGlobals['request']
}

const compileObject = async (
    obj: any,
    globals?: any,
    templating_engine: boolean | 'hog' | 'liquid' = 'hog'
): Promise<any> => {
    if (Array.isArray(obj)) {
        return Promise.all(obj.map((item) => compileObject(item, globals, templating_engine)))
    } else if (typeof obj === 'object' && obj !== null) {
        const res: Record<string, any> = {}
        for (const [key, value] of Object.entries(obj)) {
            res[key] = await compileObject(value, globals, templating_engine)
        }
        return res
    } else if (typeof obj === 'string') {
        // If the string looks like a Liquid template, render it first
        if (templating_engine === 'liquid') {
            const rendered = formatLiquidInput(obj, globals || createGlobals())
            return await compileHog(`return f'${rendered}'`)
        }
        return await compileHog(`return f'${obj}'`)
    } else {
        return obj
    }
}

export const compileInputs = async (
    template: HogFunctionTemplate | NativeTemplate,
    _inputs: Record<string, any>,
    globals?: any
): Promise<Record<string, CyclotronInputType>> => {
    const defaultInputs = template.inputs_schema.reduce(
        (acc, input) => {
            if (typeof input.default !== 'undefined') {
                acc[input.key] = input.default
            }
            return acc
        },
        {} as Record<string, CyclotronInputType>
    )

    const allInputs = { ...defaultInputs, ..._inputs }

    // Don't compile inputs that don't support templating
    const compiledEntries = await Promise.all(
        Object.entries(allInputs).map(async ([key, value]) => {
            const schema = template.inputs_schema.find((input) => input.key === key)
            if (schema?.templating === false) {
                return [key, value]
            }
            return [key, await compileObject(value, globals, schema?.templating || 'hog')]
        })
    )

    return compiledEntries.reduce(
        (acc, [key, value]) => {
            acc[key] = {
                value: allInputs[key],
                bytecode: value,
            }
            return acc
        },
        {} as Record<string, CyclotronInputType>
    )
}

const createGlobals = (
    globals: DeepPartialHogFunctionInvocationGlobals = {}
): HogFunctionInvocationGlobalsWithInputs => {
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

export class TemplateTester {
    public template: HogFunctionTemplateCompiled
    private hogExecutor: HogExecutorService
    private nativeExecutor: NativeDestinationExecutorService
    private mockHub: Hub

    private geoipService?: GeoIPService
    public geoIp?: GeoIp

    public mockFetch = jest.fn()
    public mockPrint = jest.fn()
    constructor(private _template: HogFunctionTemplate) {
        this.template = {
            ..._template,
            bytecode: [],
        }

        this.mockHub = { ...defaultConfig } as any

        this.hogExecutor = new HogExecutorService(this.mockHub)
        this.nativeExecutor = new NativeDestinationExecutorService(defaultConfig)
    }

    private getExecutor(): HogExecutorService | NativeDestinationExecutorService {
        return isNativeHogFunction({ template_id: this.template.id }) ? this.nativeExecutor : this.hogExecutor
    }

    /*
    we need transformResult to be able to test the geoip template
    the same way we did it here https://github.com/PostHog/posthog-plugin-geoip/blob/a5e9370422752eb7ea486f16c5cc8acf916b67b0/index.test.ts#L79
    */
    async beforeEach() {
        Settings.defaultZone = 'UTC'
        if (!this.geoipService) {
            this.geoipService = new GeoIPService(defaultConfig)
        }

        if (!this.geoIp) {
            this.geoIp = await this.geoipService.get()
        }

        this.template = {
            ...this._template,
            bytecode: await compileHog(this._template.code),
        }

        this.hogExecutor = new HogExecutorService(this.mockHub)
        this.nativeExecutor = new NativeDestinationExecutorService(this.mockHub)
    }

    afterEach() {
        Settings.defaultZone = 'system'
    }

    createGlobals(globals: DeepPartialHogFunctionInvocationGlobals = {}): HogFunctionInvocationGlobalsWithInputs {
        return createGlobals(globals)
    }

    async invoke(
        _inputs: Record<string, any>,
        _globals?: DeepPartialHogFunctionInvocationGlobals
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        if (this.template.mapping_templates) {
            throw new Error('Mapping templates found. Use invokeMapping instead.')
        }

        const globals = this.createGlobals(_globals)
        // Pass globals to compileInputs so Liquid templates are rendered before hog compilation
        const compiledInputs = await compileInputs(this.template, _inputs, globals)

        const { code, ...partialTemplate } = this.template
        const hogFunction: HogFunctionType = {
            ...partialTemplate,
            hog: code,
            inputs: compiledInputs,
            bytecode: this.template.bytecode,
            team_id: 1,
            enabled: true,
            mappings: this.template.mappings || null,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            deleted: false,
            template_id: this.template.id,
        }

        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)
        const invocation = createInvocation(globalsWithInputs, hogFunction)
        const transformationFunctions = getTransformationFunctions(this.geoIp!)
        const extraFunctions = invocation.hogFunction.type === 'transformation' ? transformationFunctions : {}

        return this.getExecutor().execute(invocation, { functions: extraFunctions })
    }

    async invokeMapping(
        mapping_name: string,
        _inputs: Record<string, any>,
        _globals?: DeepPartialHogFunctionInvocationGlobals,
        mapping_inputs?: Record<string, any>
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        if (!this.template.mapping_templates) {
            throw new Error('No mapping templates found')
        }

        const compiledInputs = await compileInputs(this.template, _inputs)

        const compiledMappingInputs = {
            ...this.template.mapping_templates.find((mapping) => mapping.name === mapping_name),
            inputs: mapping_inputs ?? {},
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
                        bytecode: await compileObject(value),
                    }
                })
        )

        const inputsObj = processedInputs.reduce(
            (acc, item) => {
                acc[item.key] = {
                    value: item.value,
                    bytecode: item.bytecode,
                }
                return acc
            },
            {} as Record<string, CyclotronInputType>
        )

        compiledMappingInputs.inputs = inputsObj

        const { code, ...partialTemplate } = this.template
        const hogFunction: HogFunctionType = {
            ...partialTemplate,
            hog: code,
            team_id: 1,
            enabled: true,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            deleted: false,
            inputs: compiledInputs,
            mappings: [compiledMappingInputs],
        }

        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(
            hogFunction,
            this.createGlobals(_globals),
            compiledMappingInputs.inputs
        )

        const invocation = createInvocation(globalsWithInputs, hogFunction)

        return this.getExecutor().execute(invocation)
    }

    async invokeFetchResponse(
        invocation: CyclotronJobInvocationHogFunction,
        response: { status: number; body: Record<string, any> }
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const modifiedInvocation = cloneInvocation(invocation)

        modifiedInvocation.state.vmState!.stack.push({
            status: response.status,
            body: response.body,
        })

        const result = await this.hogExecutor.execute(modifiedInvocation)
        result.logs = this.logsForSnapshot(result.logs)

        return result
    }

    logsForSnapshot(logs: MinimalLogEntry[]): MinimalLogEntry[] {
        return logs.map((x) => {
            if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                x.message = 'Function completed in [REPLACED]'
            }
            return x
        })
    }
}

export const createAdDestinationPayload = (
    globals?: DeepPartialHogFunctionInvocationGlobals
): DeepPartialHogFunctionInvocationGlobals => {
    let defaultPayload = {
        event: {
            properties: {},
            event: 'Order Completed',
            uuid: 'event-id',
            timestamp: '2025-01-01T00:00:00Z',
            distinct_id: 'distinct-id',
            elements_chain: '',
            url: 'https://us.posthog.com/projects/1/events/1234',
        },
        person: {
            id: 'person-id',
            properties: {
                email: 'example@posthog.com',
                ttclid: 'tiktok-id',
                gclid: 'google-id',
                sccid: 'snapchat-id',
                rdt_cid: 'reddit-id',
                phone: '+1234567890',
                external_id: '1234567890',
                first_name: 'Max',
                last_name: 'AI',
            },
            url: 'https://us.posthog.com/projects/1/persons/1234',
        },
    }

    defaultPayload = merge(defaultPayload, globals ?? {})

    return defaultPayload
}

export const generateTestData = (
    seedName: string,
    input_schema: HogFunctionInputSchemaType[],
    requiredFieldsOnly: boolean = false
): Record<string, any> => {
    const generateValue = (input: HogFunctionInputSchemaType): any => {
        const chance = new Chance(seedName)

        if (Array.isArray(input.choices)) {
            const choice = chance.pickone(input.choices)
            return choice.value
        }

        const getFormat = (input: HogFunctionInputSchemaType): string => {
            if (input.key === 'url') {
                return 'uri'
            } else if (input.key === 'email') {
                return 'email'
            } else if (input.key === 'uuid') {
                return 'uuid'
            } else if (input.key === 'phone') {
                return 'phone'
            }
            return 'string'
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
                switch (getFormat(input)) {
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
                    case 'phone':
                        val = chance.phone()
                        break
                    default:
                        val = chance.string()
                        break
                }
                break
        }
        return val
    }

    const inputs = input_schema.reduce(
        (acc, input) => {
            if (input.required || requiredFieldsOnly === false) {
                acc[input.key] = input.default ?? generateValue(input)
            }
            return acc
        },
        {} as Record<string, any>
    )

    return inputs
}
