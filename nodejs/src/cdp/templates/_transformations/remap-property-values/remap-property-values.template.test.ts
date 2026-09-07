import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './remap-property-values.template'

describe('remap-property-values.template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (inputs: Record<string, any>, globals: HogFunctionInvocationGlobals): Promise<any> => {
        const response = await tester.invoke(inputs, globals)
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        return response.execResult as any
    }

    it('remaps a listed value and leaves other values alone', async () => {
        const globals = tester.createGlobals({
            event: {
                properties: {
                    group_code: 'grp_a1',
                    other_code: 'grp_a1',
                },
            },
        })

        const result = await invoke({ propertyNames: 'group_code', valueMapping: { grp_a1: 'grp_b2' } }, globals)

        expect(result.properties.group_code).toBe('grp_b2')
        expect(result.properties.other_code).toBe('grp_a1')
    })

    it('remaps person properties set on the event', async () => {
        const globals = tester.createGlobals({
            event: {
                properties: {
                    $set: { plan: 'starter' },
                    $set_once: { plan: 'starter' },
                },
            },
        })

        const result = await invoke({ propertyNames: 'plan', valueMapping: { starter: 'free' } }, globals)

        expect(result.properties.$set.plan).toBe('free')
        expect(result.properties.$set_once.plan).toBe('free')
    })

    it('remaps several properties listed together', async () => {
        const globals = tester.createGlobals({
            event: {
                properties: {
                    region: 'emea',
                    billing_region: 'emea',
                },
            },
        })

        const result = await invoke(
            { propertyNames: ' region , billing_region ', valueMapping: { emea: 'europe' } },
            globals
        )

        expect(result.properties.region).toBe('europe')
        expect(result.properties.billing_region).toBe('europe')
    })

    it('matches a numeric value by its string form', async () => {
        const globals = tester.createGlobals({
            event: {
                properties: {
                    tier: 1,
                },
            },
        })

        const result = await invoke({ propertyNames: 'tier', valueMapping: { '1': 'gold' } }, globals)

        expect(result.properties.tier).toBe('gold')
    })

    it('leaves the event alone when the property is missing', async () => {
        const globals = tester.createGlobals({
            event: {
                properties: {
                    other: 'value',
                },
            },
        })

        const result = await invoke({ propertyNames: 'group_code', valueMapping: { grp_a1: 'grp_b2' } }, globals)

        expect(result.properties).toEqual({ other: 'value' })
    })
})
