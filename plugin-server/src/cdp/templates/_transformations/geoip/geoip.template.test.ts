import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './geoip.template'

describe('geoip template', () => {
    const tester = new TemplateTester(template)

    const mockGeoipLookup = jest.fn()
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        mockGeoipLookup.mockReturnValue({
            city: { names: { en: 'Sydney' } },
            country: { names: { en: 'Australia' } },
        })
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))

        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '127.0.0.1',
                },
            },
        })
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke({}, mockGlobals)
        // TODO: Add support for the hog function exector to do the geoip lookup stuff
        expect(response.error).toBeUndefined()
        // TODO: Add the response to the hog executor
        expect(response.result).toMatchInlineSnapshot()
    })
})
