import merge from 'deepmerge'

import { defaultConfig } from '~/config/config'
import { GeoIp, GeoIPService } from '~/utils/geoip'

import { Hub } from '../../../types'
import { cleanNullValues } from '../../hog-transformations/transformation-functions'
import { buildGlobalsWithInputs, HogExecutorService } from '../../services/hog-executor.service'
import {
    CyclotronJobInvocationHogFunction,
    HogFunctionInputType,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionQueueParametersFetchResponse,
    HogFunctionType,
} from '../../types'
import { cloneInvocation } from '../../utils/invocation-utils'
import { createInvocation } from '../../utils/invocation-utils'
import { compileHog } from '../compiler'
import { HogFunctionTemplate, HogFunctionTemplateCompiled } from '../types'

export type DeepPartialHogFunctionInvocationGlobals = {
    event?: Partial<HogFunctionInvocationGlobals['event']>
    person?: Partial<HogFunctionInvocationGlobals['person']>
    source?: Partial<HogFunctionInvocationGlobals['source']>
    request?: HogFunctionInvocationGlobals['request']
}

export class TemplateTester {
    public template: HogFunctionTemplateCompiled
    private executor: HogExecutorService
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

        this.mockHub = {} as any

        this.executor = new HogExecutorService(this.mockHub)
    }

    /*
    we need transformResult to be able to test the geoip template
    the same way we did it here https://github.com/PostHog/posthog-plugin-geoip/blob/a5e9370422752eb7ea486f16c5cc8acf916b67b0/index.test.ts#L79
    */
    async beforeEach() {
        if (!this.geoipService) {
            this.geoipService = new GeoIPService(defaultConfig)
        }

        if (!this.geoIp) {
            this.geoIp = await this.geoipService.get()
        }

        this.template = {
            ...this._template,
            bytecode: await compileHog(this._template.hog),
        }

        this.mockHub = { mmdb: undefined } as any

        this.executor = new HogExecutorService(this.mockHub)
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
                properties: { $current_url: 'https://example.com', ...(globals.event?.properties ?? {}) },
                timestamp: '2024-01-01T00:00:00Z',
                elements_chain: '',
                url: 'https://us.posthog.com/projects/1/events/1234',
                ...globals.event,
            },
            person: {
                id: 'person-id',
                name: 'person-name',
                properties: { email: 'example@posthog.com', ...(globals.person?.properties ?? {}) },
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

        const compiledEntries = await Promise.all(
            Object.entries(allInputs).map(async ([key, value]) => [key, await this.compileObject(value)])
        )

        return compiledEntries.reduce((acc, [key, value]) => {
            acc[key] = {
                value: allInputs[key],
                bytecode: value,
            }
            return acc
        }, {} as Record<string, HogFunctionInputType>)
    }

    async invoke(_inputs: Record<string, any>, _globals?: DeepPartialHogFunctionInvocationGlobals) {
        if (this.template.mapping_templates) {
            throw new Error('Mapping templates found. Use invokeMapping instead.')
        }

        const compiledInputs = await this.compileInputs(_inputs)
        const globals = this.createGlobals(_globals)

        const hogFunction: HogFunctionType = {
            ...this.template,
            inputs: compiledInputs,
            bytecode: this.template.bytecode,
            team_id: 1,
            enabled: true,
            mappings: this.template.mappings || null,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            is_addon_required: false,
            deleted: false,
        }

        const globalsWithInputs = buildGlobalsWithInputs(globals, hogFunction.inputs)
        const invocation = createInvocation(globalsWithInputs, hogFunction)

        const transformationFunctions = {
            geoipLookup: (val: unknown): any => {
                return typeof val === 'string' ? this.geoIp?.city(val) : null
            },
            cleanNullValues,
        }

        const extraFunctions = invocation.hogFunction.type === 'transformation' ? transformationFunctions : {}

        return this.executor.execute(invocation, { functions: extraFunctions })
    }

    async invokeMapping(
        mapping_name: string,
        _inputs: Record<string, any>,
        _globals?: DeepPartialHogFunctionInvocationGlobals,
        mapping_inputs?: Record<string, any>
    ) {
        if (!this.template.mapping_templates) {
            throw new Error('No mapping templates found')
        }

        const compiledInputs = await this.compileInputs(_inputs)

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

        const globalsWithInputs = buildGlobalsWithInputs(this.createGlobals(_globals), {
            ...compiledInputs,
            ...compiledMappingInputs.inputs,
        })
        const invocation = createInvocation(globalsWithInputs, {
            ...this.template,
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
    invokeFetchResponse(
        invocation: CyclotronJobInvocationHogFunction,
        response: HogFunctionQueueParametersFetchResponse
    ) {
        const modifiedInvocation = cloneInvocation(invocation, {
            queue: 'hog' as const,
            queueParameters: response,
        })

        return this.executor.execute(modifiedInvocation)
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
