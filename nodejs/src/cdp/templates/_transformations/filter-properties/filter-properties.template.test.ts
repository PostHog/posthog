import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './filter-properties.template'

describe('filter-properties.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should set properties to null', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        email: 'test@example.com',
                        name: 'Test User',
                    },
                    custom_prop: 'value',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$set.email, $set.name, custom_prop',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $set: {
                    email: null,
                    name: null,
                },
                custom_prop: null,
            },
        })
    })

    it('should handle a comprehensive list of properties to filter', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '1.2.3.4',
                    $geoip_latitude: 40.7128,
                    $geoip_longitude: -74.006,
                    $set: {
                        $geoip_latitude: 40.7128,
                        $geoip_longitude: -74.006,
                        name: 'Test User',
                        email: 'test@example.com',
                    },
                    $set_once: {
                        $initial_geoip_latitude: 40.7128,
                        $initial_geoip_longitude: -74.006,
                        first_seen: '2024-01-01',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter:
                    '$ip,$geoip_latitude,$geoip_longitude,$set.$geoip_latitude,$set.$geoip_longitude,$set_once.$initial_geoip_latitude,$set_once.$initial_geoip_longitude',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $ip: null,
                $geoip_latitude: null,
                $geoip_longitude: null,
                $set: {
                    $geoip_latitude: null,
                    $geoip_longitude: null,
                    name: 'Test User',
                    email: 'test@example.com',
                },
                $set_once: {
                    $initial_geoip_latitude: null,
                    $initial_geoip_longitude: null,
                    first_seen: '2024-01-01',
                },
            },
        })
    })

    it('should handle filtering out entire $set object', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        email: 'test@example.com',
                        name: 'Test User',
                        profile: {
                            age: 25,
                            location: 'NYC',
                        },
                        preferences: {
                            theme: 'dark',
                            notifications: true,
                        },
                    },
                    $set_once: {
                        first_seen: '2024-01-01',
                    },
                    custom_prop: 'value',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$set',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $set: null,
                $set_once: {
                    first_seen: '2024-01-01',
                },
                custom_prop: 'value',
            },
        })
    })

    it('should handle deeply nested properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        user: {
                            profile: {
                                email: 'test@example.com',
                                name: 'Test User',
                            },
                        },
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$set.user.profile.email, $set.user.profile.name',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $set: {
                    user: {
                        profile: {
                            email: null,
                            name: null,
                        },
                    },
                },
            },
        })
    })

    it('should handle non-existent properties gracefully', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        email: 'test@example.com',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$set.nonexistent, $set.email, nonexistent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $set: {
                    email: null,
                },
            },
        })
    })

    it('should handle empty event properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {},
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$set.email, custom_prop',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {},
        })
    })

    it('should handle empty properties list', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        email: 'test@example.com',
                    },
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
        expect(response.execResult).toMatchObject({
            properties: {
                $set: {
                    email: 'test@example.com',
                },
            },
        })
    })

    it('should handle falsy values correctly', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        zero: 0,
                        false_value: false,
                        empty_string: '',
                        null_value: null,
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$set.zero, $set.false_value, $set.empty_string, $set.null_value',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $set: {
                    zero: null,
                    false_value: null,
                    empty_string: null,
                    null_value: null,
                },
            },
        })
    })
})
