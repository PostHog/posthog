import { City, Reader } from '@maxmind/geoip2-node'
import { readFileSync } from 'fs'
import { join } from 'path'
import { brotliDecompressSync } from 'zlib'

import { buildGlobalsWithInputs, HogExecutor } from '../../hog-executor'
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
    private executor: HogExecutor
    private mockHub: Hub

    public mockFetch = jest.fn()
    public mockPrint = jest.fn()
    constructor(private _template: HogFunctionTemplate) {
        this.template = {
            ..._template,
            bytecode: [],
        }

        const mockHub = {} as any
        const mockHogFunctionManager = {} as any

        this.executor = new HogExecutor(mockHub, mockHogFunctionManager)
    }

    /*
    we need transformResult to be able to test the geoip template
    the same way we did it here https://github.com/PostHog/posthog-plugin-geoip/blob/a5e9370422752eb7ea486f16c5cc8acf916b67b0/index.test.ts#L79
    */
    async beforeEach(transformResult?: (res: City) => any, skipMMDB?: boolean) {
        this.template = {
            ...this._template,
            bytecode: await compileHog(this._template.hog),
        }

        this.mockHub = { mmdb: undefined } as any

        if (!skipMMDB) {
            try {
                const mmdbBrotliContents = readFileSync(
                    join(__dirname, '../../../../tests/assets/GeoLite2-City-Test.mmdb.br')
                )
                const mmdbBuffer = brotliDecompressSync(mmdbBrotliContents)
                const mmdb = Reader.openBuffer(mmdbBuffer)

                this.mockHub.mmdb = transformResult
                    ? {
                          city: (ipAddress: string) => {
                              const res = mmdb.city(ipAddress)
                              return transformResult(res)
                          },
                      }
                    : mmdb
            } catch (error) {
                throw new Error(`Failed to load MMDB file: ${error}`)
            }
        }

        const mockHogFunctionManager = {} as any
        this.executor = new HogExecutor(this.mockHub, mockHogFunctionManager)
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

    async invoke(_inputs: Record<string, any>, _globals?: DeepPartialHogFunctionInvocationGlobals) {
        const defaultInputs = this.template.inputs_schema.reduce((acc, input) => {
            if (typeof input.default !== 'undefined') {
                acc[input.key] = {
                    value: input.default,
                }
            }
            return acc
        }, {} as Record<string, HogFunctionInputType>)

        const allInputs = { ...defaultInputs, ..._inputs }

        const compiledEntries = await Promise.all(
            Object.entries(allInputs).map(async ([key, value]) => [key, await this.compileObject(value)])
        )

        const compiledInputs = compiledEntries.reduce((acc, [key, value]) => {
            acc[key] = {
                value: allInputs[key],
                bytecode: value,
            }
            return acc
        }, {} as Record<string, HogFunctionInputType>)

        const globals = this.createGlobals(_globals)

        const hogFunction: HogFunctionType = {
            ...this.template,
            inputs: compiledInputs,
            bytecode: this.template.bytecode,
            team_id: 1,
            enabled: true,
            mappings: this.template.mappings || null,
        }

        const globalsWithInputs = buildGlobalsWithInputs(globals, hogFunction.inputs)
        const invocation = createInvocation(globalsWithInputs, hogFunction)

        const transformationFunctions = {
            geoipLookup: (ipAddress: unknown) => {
                if (typeof ipAddress !== 'string') {
                    return null
                }
                if (!this.mockHub.mmdb) {
                    return null
                }
                try {
                    return this.mockHub.mmdb.city(ipAddress)
                } catch {
                    return null
                }
            },
        }

        const extraFunctions = invocation.hogFunction.type === 'transformation' ? transformationFunctions : {}

        return this.executor.execute(invocation, { functions: extraFunctions })
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
