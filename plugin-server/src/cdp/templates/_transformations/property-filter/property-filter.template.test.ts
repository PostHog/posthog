import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './property-filter.template'

describe('property-filter.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should filter out top-level properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                event: 'test_event',
                properties: {
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'distinct_id',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).distinct_id).toBeUndefined()
        expect((response.execResult as any).event).toBe('test_event')
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })

    it('should filter out properties in event.properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    $ip: '127.0.0.1',
                    $set: {
                        $ip: '192.168.1.1',
                        email: 'test@example.com',
                    },
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$ip,$set.$ip',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).distinct_id).toBe('user123')
        expect((response.execResult as any).properties.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$set.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$set.email).toBe('test@example.com')
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })

    it('should handle empty propertiesToFilter', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    $ip: '127.0.0.1',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).distinct_id).toBe('user123')
        expect((response.execResult as any).properties.$ip).toBe('127.0.0.1')
    })

    it('should filter out deeply nested properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    user: {
                        profile: {
                            settings: {
                                email: 'test@example.com',
                                api_key: 'secret-key',
                                preferences: {
                                    theme: 'dark',
                                },
                            },
                        },
                    },
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'user.profile.settings.api_key,user.profile.settings.preferences.theme',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).distinct_id).toBe('user123')
        expect((response.execResult as any).properties.user.profile.settings.email).toBe('test@example.com')
        expect((response.execResult as any).properties.user.profile.settings.api_key).toBeUndefined()
        expect((response.execResult as any).properties.user.profile.settings.preferences.theme).toBeUndefined()
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })

    it('should handle property paths with special characters and mixed casing', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    user_data: {
                        profile_info: {
                            api_key: 'secret',
                            userName: 'John',
                        },
                    },
                    $set: {
                        last_login: '2024-01-01',
                        UPPERCASE_PROP: 'test',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'user_data.profile_info.api_key,$SET.last_login',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.user_data.profile_info.api_key).toBeUndefined()
        expect((response.execResult as any).properties.user_data.profile_info.userName).toBe('John')
        expect((response.execResult as any).properties.$set.last_login).toBeUndefined()
        expect((response.execResult as any).properties.$set.UPPERCASE_PROP).toBe('test')
    })

    it('should handle filtering non-existent properties while keeping siblings', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    parent: {
                        child1: {
                            value: 'keep-me',
                        },
                        child2: {
                            value: 'also-keep-me',
                        },
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'parent.child3.value,parent.child1.nonexistent,parent.child2.value',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.parent.child1.value).toBe('keep-me')
        expect((response.execResult as any).properties.parent.child2.value).toBeUndefined()
        // These shouldn't exist but also shouldn't cause errors
        expect((response.execResult as any).properties.parent.child3).toBeUndefined()
        expect((response.execResult as any).properties.parent.child1.nonexistent).toBeUndefined()
    })

    it('should handle complex PostHog property paths', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    '$feature/onboarding/enable-new-flow': true,
                    '$feature/billing/beta': false,
                    '$experiment/checkout-test-001/variant': 'control',
                    $geoip_city_name: 'London',
                    'app/version': '1.2.3',
                    $plugins: {
                        'plugin/custom/sensitive-data': {
                            'auth/api_key': 'secret-123',
                            'user/metadata': {
                                'session/device_id': 'test-device',
                            },
                        },
                    },
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter:
                    '$feature/onboarding/enable-new-flow,$plugins.plugin/custom/sensitive-data.auth/api_key,$geoip_city_name',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties['$feature/onboarding/enable-new-flow']).toBeUndefined()
        expect((response.execResult as any).properties['$feature/billing/beta']).toBe(false)
        expect((response.execResult as any).properties['$experiment/checkout-test-001/variant']).toBe('control')
        expect((response.execResult as any).properties.$geoip_city_name).toBeUndefined()
        expect((response.execResult as any).properties['app/version']).toBe('1.2.3')
        expect(
            (response.execResult as any).properties.$plugins['plugin/custom/sensitive-data']['auth/api_key']
        ).toBeUndefined()
        expect(
            (response.execResult as any).properties.$plugins['plugin/custom/sensitive-data']['user/metadata'][
                'session/device_id'
            ]
        ).toBe('test-device')
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })
})
