import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'

const createEvent = (event: Partial<PluginEvent>): PluginEvent =>
    ({
        distinct_id: '1',
        event: '$pageview',
        properties: {
            ...event.properties,
        },
        ...event,
    }) as unknown as PluginEvent

describe('taxonomy-plugin', () => {
    describe('event name transformations', () => {
        it('should transform to camelCase', () => {
            const testCases = [
                ['user_signed_up', 'userSignedUp'],
                // NOTE: This is how the legacy plugin worked - its a bug
                ['User Logged In', 'user Logged In'],
                ['checkout-completed', 'checkoutCompleted'],
            ]

            for (const [input, expected] of testCases) {
                const event = createEvent({ event: input })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'camelCase' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(expected)
            }
        })

        it('should transform to PascalCase', () => {
            const testCases = [
                ['user_signed_up', 'UserSignedUp'],
                ['user logged in', 'UserLoggedIn'],
                ['checkout-completed', 'CheckoutCompleted'],
            ]

            for (const [input, expected] of testCases) {
                const event = createEvent({ event: input })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'PascalCase' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(expected)
            }
        })

        it('should transform to snake_case', () => {
            const testCases = [
                ['userSignedUp', 'user_signed_up'],
                // NOTE: This is how the legacy plugin worked - its a bug
                ['User Logged In', 'user _logged _in'],
                ['checkout-completed', 'checkout_completed'],
            ]

            for (const [input, expected] of testCases) {
                const event = createEvent({ event: input })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'snake_case' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(expected)
            }
        })

        it('should transform to kebab-case', () => {
            const testCases = [
                ['userSignedUp', 'user-signed-up'],
                ['User Logged In', 'user -logged -in'], // NOTE: This is how the legacy plugin worked - its a bug
                ['checkout_completed', 'checkout-completed'],
            ]

            for (const [input, expected] of testCases) {
                const event = createEvent({ event: input })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'kebab-case' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(expected)
            }
        })

        it('should transform to spaces', () => {
            const testCases = [
                ['userSignedUp', 'user signed up'],
                ['user-logged-in', 'user logged in'],
                ['checkout_completed', 'checkout completed'],
            ]

            for (const [input, expected] of testCases) {
                const event = createEvent({ event: input })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'spaces in between' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(expected)
            }
        })
    })

    describe('special cases', () => {
        it('should not transform PostHog system events starting with $', () => {
            const testCases = ['$pageview', '$autocapture', '$feature_flag_called']

            for (const systemEvent of testCases) {
                const event = createEvent({ event: systemEvent })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'camelCase' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(systemEvent)
            }
        })

        it('should not transform skipped PostHog events', () => {
            const testCases = ['survey shown', 'survey sent', 'survey dismissed']

            for (const surveyEvent of testCases) {
                const event = createEvent({ event: surveyEvent })
                const result = processEvent(event, {
                    config: { defaultNamingConvention: 'camelCase' },
                    global: {},
                } as unknown as LegacyTransformationPluginMeta)
                expect(result.event).toBe(surveyEvent)
            }
        })

        it('should preserve other event properties', () => {
            const event = createEvent({ event: 'user_signed_up', properties: { foo: 'bar' } })
            const result = processEvent(event, {
                config: { defaultNamingConvention: 'camelCase' },
                global: {},
            } as unknown as LegacyTransformationPluginMeta)

            expect(result).toEqual({
                ...event,
                event: 'userSignedUp',
            })
        })
    })
})
