import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './flatten-properties.template'

describe('flatten-properties.template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (properties: Record<string, any>, event = 'test'): Promise<any> => {
        const globals: HogFunctionInvocationGlobals = tester.createGlobals({ event: { event, properties } })
        const response = await tester.invoke({ separator: '__' }, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return (response.execResult as any).properties
    }

    it('flattens nested objects and arrays while keeping the originals', async () => {
        const properties = await invoke({
            a: { b: { c: { d: { e: { f: 'nested under e' }, z: 'nested under d' }, z: 'nested under c' } } },
            w: { array: [{ z: 'nested in w array' }] },
            x: 'not nested',
        })

        expect(properties.x).toBe('not nested')
        expect(properties.a).toEqual({
            b: { c: { d: { e: { f: 'nested under e' }, z: 'nested under d' }, z: 'nested under c' } },
        })
        expect(properties.a__b__c__d__e__f).toBe('nested under e')
        expect(properties.a__b__c__d__z).toBe('nested under d')
        expect(properties.a__b__c__z).toBe('nested under c')
        expect(properties.w__array__0__z).toBe('nested in w array')
    })

    it('flattens within $set and $set_once under a fresh prefix', async () => {
        const properties = await invoke({
            $set: { example: { company_size: 20, category: ['a', 'b'] } },
            $set_once: { example: { company_size: 20 } },
        })

        expect(properties.$set.example__company_size).toBe(20)
        expect(properties.$set.example__category__0).toBe('a')
        expect(properties.$set.example__category__1).toBe('b')
        expect(properties.$set.example).toEqual({ company_size: 20, category: ['a', 'b'] })
        expect(properties.$set_once.example__company_size).toBe(20)
        // The $set prefix is not carried into the flattened keys.
        expect(properties.$set__example__company_size).toBeUndefined()
    })

    it('keeps a separator for an empty property name so siblings survive', async () => {
        const properties = await invoke({
            name: 'kept',
            '': { name: 'nested under the empty key' },
            $set: { name: 'kept in $set', '': { name: 'nested under the empty key in $set' } },
        })

        expect(properties.name).toBe('kept')
        expect(properties.__name).toBe('nested under the empty key')
        expect(properties.$set.name).toBe('kept in $set')
        expect(properties.$set.__name).toBe('nested under the empty key in $set')
    })

    it('keeps a nested empty object as a flattened leaf', async () => {
        const properties = await invoke({
            a: { b: {} },
            list: { items: [] },
            $set: { a: { b: {} } },
        })

        expect(properties.a__b).toEqual({})
        expect(properties.$set.a__b).toEqual({})
        // An empty array has no items to enumerate, so it produces no flattened key.
        expect(properties.list__items).toBeUndefined()
    })

    it('leaves internal deny-listed properties nested', async () => {
        const properties = await invoke({
            $groups: { org: { id: 1 } },
            keep: { nested: 'value' },
        })

        expect(properties.$groups).toEqual({ org: { id: 1 } })
        expect(properties.$groups__org__id).toBeUndefined()
        expect(properties.keep__nested).toBe('value')
    })

    it('skips events on the event deny list', async () => {
        const properties = await invoke({ any: [{ nested: 'property' }] }, 'organization usage report')

        expect(properties).toEqual({ any: [{ nested: 'property' }] })
    })
})
