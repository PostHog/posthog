import { createHogFunction } from '../_tests/fixtures'
import { template as geoipTemplate } from '../templates/_transformations/geoip/geoip.template'
import { compileHog } from '../templates/compiler'
import { HogFunctionType } from '../types'
import { createInvocation } from '../utils/invocation-utils'
import { geoipNoopResult, hogTransformationGeoipNoopSkips } from './geoip-noop'

const VALID_IP = '203.0.113.7'

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

describe('geoipNoopResult', () => {
    let shippedBytecode: any[]
    let modifiedBytecode: any[]

    beforeAll(async () => {
        shippedBytecode = await compileHog(geoipTemplate.code)
        modifiedBytecode = await compileHog(geoipTemplate.code.replace('geoip disabled or no ip.', 'geoip skipped.'))
    })

    it.each([
        {
            name: 'the geoip template id with the shipped bytecode',
            templateId: 'template-geoip',
            shipped: true,
            eligible: true,
        },
        {
            name: 'the geoip template id with modified bytecode',
            templateId: 'template-geoip',
            shipped: false,
            eligible: false,
        },
        {
            name: 'another template id with the shipped bytecode',
            templateId: 'template-ip-anonymization',
            shipped: true,
            eligible: false,
        },
        { name: 'no template id with the shipped bytecode', templateId: undefined, shipped: true, eligible: false },
    ])('eligible is $eligible for $name', ({ templateId, shipped, eligible }) => {
        const invocation = createGeoipInvocation(
            { template_id: templateId, bytecode: shipped ? shippedBytecode : modifiedBytecode },
            { $geoip_disable: true, $ip: VALID_IP }
        )

        expect(geoipNoopResult(invocation) !== null).toBe(eligible)
    })

    it.each([
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
    ])('skipped is $skipped when $name', ({ properties, skipped }) => {
        const invocation = createGeoipInvocation({ bytecode: shippedBytecode }, properties)

        expect(geoipNoopResult(invocation) !== null).toBe(skipped)
    })

    it('returns the input event as a finished result with the template logs', async () => {
        const invocation = createGeoipInvocation({ bytecode: shippedBytecode }, { $geoip_disable: true, $ip: VALID_IP })
        const skipsBefore = await skipCount()

        const result = geoipNoopResult(invocation)

        expect(result?.finished).toBe(true)
        expect(result?.error).toBeUndefined()
        expect(result?.execResult).toBe(invocation.state.globals.event)
        expect(result?.logs.map(({ level, message }) => ({ level, message }))).toEqual([
            { level: 'info', message: 'geoip disabled or no ip.' },
            { level: 'debug', message: expect.stringMatching(/^Function completed in [\d.]+ms\.$/) },
        ])
        expect((await skipCount()) - skipsBefore).toBe(1)
    })
})
