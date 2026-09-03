import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './taxonomy.template'

describe('taxonomy.template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const rename = async (namingConvention: string, eventName: string): Promise<string> => {
        const globals: HogFunctionInvocationGlobals = tester.createGlobals({
            event: { event: eventName, properties: {} },
        })
        const response = await tester.invoke({ namingConvention }, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return (response.execResult as any).event
    }

    it.each([
        ['user_signed_up', 'userSignedUp'],
        ['User Logged In', 'userLoggedIn'],
        ['checkout-completed', 'checkoutCompleted'],
        ['userSignedUp', 'userSignedUp'],
    ])('converts %s to camelCase', async (input, expected) => {
        expect(await rename('camelCase', input)).toBe(expected)
    })

    it.each([
        ['user_signed_up', 'UserSignedUp'],
        ['user logged in', 'UserLoggedIn'],
        ['checkout-completed', 'CheckoutCompleted'],
    ])('converts %s to PascalCase', async (input, expected) => {
        expect(await rename('PascalCase', input)).toBe(expected)
    })

    it.each([
        ['userSignedUp', 'user_signed_up'],
        ['User Logged In', 'user_logged_in'],
        ['checkout-completed', 'checkout_completed'],
    ])('converts %s to snake_case', async (input, expected) => {
        expect(await rename('snake_case', input)).toBe(expected)
    })

    it.each([
        ['userSignedUp', 'user-signed-up'],
        ['User Logged In', 'user-logged-in'],
        ['checkout_completed', 'checkout-completed'],
    ])('converts %s to kebab-case', async (input, expected) => {
        expect(await rename('kebab-case', input)).toBe(expected)
    })

    it.each([
        ['userSignedUp', 'user signed up'],
        ['checkout_completed', 'checkout completed'],
    ])('converts %s to spaces', async (input, expected) => {
        expect(await rename('spaces', input)).toBe(expected)
    })

    it('leaves PostHog events and survey events untouched', async () => {
        expect(await rename('snake_case', '$pageview')).toBe('$pageview')
        expect(await rename('snake_case', 'survey sent')).toBe('survey sent')
    })
})
