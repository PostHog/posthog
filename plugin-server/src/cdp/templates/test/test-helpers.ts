import { defaultConfig } from '~/src/config/config'
import { GeoIp, GeoIPService } from '~/src/utils/geoip'

import { Hub } from '../../../types'
import { cleanNullValues } from '../../hog-transformations/transformation-functions'
import { buildGlobalsWithInputs, HogExecutorService } from '../../services/hog-executor.service'
import {
    HogFunctionInputType,
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionQueueParametersFetchResponse,
    HogFunctionType,
} from '../../types'
import { createInvocation } from '../../utils'
import { compileHog } from '../compiler'
import { HogFunctionTemplate, HogFunctionTemplateCompiled } from '../types'

export type DeepPartialHogFunctionInvocationGlobals = {
    event?: Partial<HogFunctionInvocationGlobals['event']>
    person?: Partial<HogFunctionInvocationGlobals['person']>
    source?: Partial<HogFunctionInvocationGlobals['source']>
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
            throw new Error('Mapping templates found. Use invokeMappings instead.')
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

    async invokeMappings(
        _inputs: Record<string, any>,
        _globals?: DeepPartialHogFunctionInvocationGlobals,
        _mappingInputs: Record<string, any> = {}
    ) {
        if (!this.template.mapping_templates) {
            throw new Error('No mapping templates found')
        }

        const compiledInputs = await this.compileInputs(_inputs)

        const compiledMappingInputs = this.template.mapping_templates.map((mapping) => ({
            ...mapping,
            inputs: {},
        }))

        await Promise.all(
            compiledMappingInputs.map(async (mapping) => {
                if (!mapping.inputs_schema) {
                    return
                }

                const defaultMappingInputs = mapping.inputs_schema.reduce((acc, input) => {
                    if (typeof input.default !== 'undefined') {
                        acc[input.key] = input.default
                    }
                    return acc
                }, {} as Record<string, HogFunctionInputType>)

                const allMappingInputs = { ...defaultMappingInputs, ..._mappingInputs }

                const compiledMappingEntries = await Promise.all(
                    Object.entries(allMappingInputs).map(async ([key, value]) => [key, await this.compileObject(value)])
                )

                const mappingInputsObj = compiledMappingEntries.reduce((acc, [key, value]) => {
                    acc[key] = {
                        value: allMappingInputs[key],
                        bytecode: value,
                    }
                    return acc
                }, {} as Record<string, HogFunctionInputType>)

                mapping.inputs = mappingInputsObj
            })
        )

        const invocations = this.executor.buildHogFunctionInvocations(
            [
                {
                    ...this.template,
                    team_id: 1,
                    enabled: true,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                    deleted: false,
                    inputs: compiledInputs,
                    mappings: compiledMappingInputs,
                },
            ],
            this.createGlobals(_globals)
        )

        return invocations.invocations.map((invocation) => this.executor.execute(invocation))
    }

    invokeFetchResponse(invocation: HogFunctionInvocation, response: HogFunctionQueueParametersFetchResponse) {
        const modifiedInvocation = {
            ...invocation,
            queue: 'hog' as const,
            queueParameters: response,
        }

        return this.executor.execute(modifiedInvocation)
    }
}
