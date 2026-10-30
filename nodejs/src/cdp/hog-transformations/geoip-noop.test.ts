import { GeoIPService } from '~/common/utils/geoip'

import shippedSources from '../../../tests/fixtures/geoip-template-sources.json'
import { createHogFunction } from '../_tests/fixtures'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogInputsService } from '../services/hog-inputs.service'
import { template as geoipTemplate } from '../templates/_transformations/geoip/geoip.template'
import { compileHog } from '../templates/compiler'
import { CyclotronJobInvocationResult, HogFunctionType } from '../types'
import { createInvocation } from '../utils/invocation-utils'
import { geoipNoopResult, hogTransformationGeoipNoopSkips } from './geoip-noop'
import { RustVmExecutor } from './rust-vm-executor'
import { getTransformationFunctions } from './transformation-functions'

const VALID_IP = '89.160.20.129'
const NOOP_LOG = 'geoip disabled or no ip.'

const createGeoipInvocation = (overrides: Partial<HogFunctionType>, properties: Record<string, unknown>) =>
    createInvocation(
        {
            project: { id: 1, name: '', url: 'http://localhost' },
            event: {
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties,
                elements_chain: '',
                timestamp: '2024-01-01T00:00:00Z',
                url: '',
            },
            inputs: {},
        },
        createHogFunction({ type: 'transformation', template_id: 'template-geoip', ...overrides })
    )

const skipCount = async (): Promise<number> => (await hogTransformationGeoipNoopSkips.get()).values[0]?.value ?? 0

const tookEarlyReturn = (result: CyclotronJobInvocationResult): boolean =>
    !result.error && result.logs.some(({ level, message }) => level === 'info' && message === NOOP_LOG)

describe('geoipNoopResult', () => {
    const currentSource = geoipTemplate.code
    const eligibleSources = shippedSources.filter(({ eligible }) => eligible)
    const bytecodeBySource = new Map<string, any[]>()
    let nodeVm: HogExecutorService
    let rustVm: RustVmExecutor
    let transformationFunctions: ReturnType<typeof getTransformationFunctions>

    beforeAll(async () => {
        for (const { source } of eligibleSources) {
            bytecodeBySource.set(source, await compileHog(source))
        }
        const mmdbPath = process.env.MMDB_FILE_LOCATION!
        nodeVm = new HogExecutorService({ executionTimeoutMs: 1000 }, {} as HogInputsService)
        rustVm = new RustVmExecutor({ mmdbPath })
        transformationFunctions = getTransformationFunctions(await new GeoIPService(mmdbPath).get())
    })

    it.each([
        ...shippedSources.map(({ shipped, eligible, source }) => ({
            name: `the template shipped ${shipped} as saved, trimmed`,
            fn: { hog: source.trim() },
            eligible,
        })),
        { name: 'the current template code', fn: { hog: currentSource }, eligible: true },
        {
            name: 'the current template code with whitespace changed inside a string',
            fn: { hog: currentSource.replace(NOOP_LOG, 'geoip  disabled or no ip.') },
            eligible: false,
        },
        {
            name: 'the current template code with an edited statement',
            fn: { hog: currentSource.replace("print('geoip disabled or no ip.')", "print('skipped')") },
            eligible: false,
        },
        { name: 'no stored source', fn: { hog: null as unknown as string }, eligible: false },
        {
            name: 'another template id',
            fn: { hog: currentSource, template_id: 'template-ip-anonymization' },
            eligible: false,
        },
        { name: 'no template id', fn: { hog: currentSource, template_id: undefined }, eligible: false },
    ])('eligible is $eligible for $name', ({ fn, eligible }) => {
        const invocation = createGeoipInvocation(fn, { $geoip_disable: true, $ip: VALID_IP })

        expect(geoipNoopResult(invocation) !== null).toBe(eligible)
    })

    it('rejects a source with a long inner whitespace run in linear time', () => {
        const invocation = createGeoipInvocation(
            { hog: `${currentSource}${' '.repeat(80_000)}// edited` },
            { $geoip_disable: true, $ip: VALID_IP }
        )

        const start = performance.now()
        const result = geoipNoopResult(invocation)

        expect(result).toBeNull()
        expect(performance.now() - start).toBeLessThan(500)
    })

    const conditionCases = [
        { name: '$geoip_disable is true', properties: { $geoip_disable: true, $ip: VALID_IP }, skipped: true },
        {
            name: '$geoip_disable is a truthy string',
            properties: { $geoip_disable: 'yes', $ip: VALID_IP },
            skipped: true,
        },
        {
            name: '$geoip_disable is a non-zero number',
            properties: { $geoip_disable: 1, $ip: VALID_IP },
            skipped: true,
        },
        { name: '$geoip_disable is false', properties: { $geoip_disable: false, $ip: VALID_IP }, skipped: false },
        {
            name: '$geoip_disable is an empty string',
            properties: { $geoip_disable: '', $ip: VALID_IP },
            skipped: false,
        },
        { name: '$geoip_disable is missing', properties: { $ip: VALID_IP }, skipped: false },
        { name: '$ip is missing', properties: {}, skipped: true },
        { name: '$ip is null', properties: { $ip: null }, skipped: true },
        { name: '$ip is an empty string', properties: { $ip: '' }, skipped: true },
        { name: '$ip is an empty array', properties: { $ip: [] }, skipped: true },
        { name: '$ip is an empty object', properties: { $ip: {} }, skipped: true },
        { name: '$ip is a non-empty array', properties: { $ip: [VALID_IP] }, skipped: false },
        { name: '$ip is zero', properties: { $ip: 0 }, skipped: false },
        { name: '$ip is a non-zero number', properties: { $ip: 42 }, skipped: false },
        { name: '$ip is false', properties: { $ip: false }, skipped: false },
    ]

    it.each(
        eligibleSources.flatMap(({ shipped, source }) =>
            conditionCases.map((condition) => ({ ...condition, shipped, source }))
        )
    )(
        'skipped is $skipped when $name, as both vms decide (template shipped $shipped)',
        async ({ source, properties, skipped }) => {
            const fn = { hog: source, bytecode: bytecodeBySource.get(source) }
            const onNode = await nodeVm.execute(createGeoipInvocation(fn, properties), {
                functions: transformationFunctions,
            })
            const onRust = rustVm.execute(createGeoipInvocation(fn, properties), [])
            const shortcut = geoipNoopResult(createGeoipInvocation(fn, properties))

            expect(onRust).not.toBeNull()
            expect({ error: onRust!.error, execResult: onRust!.execResult }).toEqual({
                error: onNode.error,
                execResult: onNode.execResult,
            })
            expect(tookEarlyReturn(onNode)).toBe(skipped)
            expect(tookEarlyReturn(onRust!)).toBe(skipped)
            expect(shortcut !== null).toBe(skipped)
            if (shortcut) {
                for (const onVm of [onNode, onRust!]) {
                    expect(onVm.execResult).toEqual(shortcut.execResult)
                    expect(shortcut.logs.map(({ level, message }) => ({ level, message }))).toEqual(
                        onVm.logs.map(({ level, message }) => ({
                            level,
                            message: level === 'debug' ? expect.stringMatching(/^Function completed in /) : message,
                        }))
                    )
                }
            }
        }
    )

    it('returns the input event as a finished result with the template logs', async () => {
        const invocation = createGeoipInvocation({ hog: currentSource }, { $geoip_disable: true, $ip: VALID_IP })
        const skipsBefore = await skipCount()

        const result = geoipNoopResult(invocation)

        expect(result?.finished).toBe(true)
        expect(result?.error).toBeUndefined()
        expect(result?.execResult).toBe(invocation.state.globals.event)
        expect(result?.logs.map(({ level, message }) => ({ level, message }))).toEqual([
            { level: 'info', message: NOOP_LOG },
            { level: 'debug', message: expect.stringMatching(/^Function completed in [\d.]+ms\.$/) },
        ])
        expect((await skipCount()) - skipsBefore).toBe(1)
    })
})
