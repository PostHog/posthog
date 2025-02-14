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
                includeSetProperties: false,
                includeSetOnceProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).distinct_id).toBeUndefined()
        expect((response.execResult as any).event).toBe('test_event')
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })

    it('should not filter properties from $set and $set_once when toggles are off', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    sensitive: 'remove-me',
                    safe_property: 'keep-me',
                    $set: {
                        sensitive: 'should-stay',
                        email: 'test@example.com',
                    },
                    $set_once: {
                        sensitive: 'should-also-stay',
                        username: 'test-user',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'sensitive',
                includeSetProperties: false,
                includeSetOnceProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.sensitive).toBeUndefined()
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
        expect((response.execResult as any).properties.$set.sensitive).toBe('should-stay')
        expect((response.execResult as any).properties.$set_once.sensitive).toBe('should-also-stay')
    })

    it('should filter properties from $set when enabled', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    sensitive: 'remove-me',
                    $set: {
                        sensitive: 'should-be-removed',
                        email: 'test@example.com',
                    },
                    $set_once: {
                        sensitive: 'should-stay',
                        username: 'test-user',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'sensitive',
                includeSetProperties: true,
                includeSetOnceProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.sensitive).toBeUndefined()
        expect((response.execResult as any).properties.$set.sensitive).toBeUndefined()
        expect((response.execResult as any).properties.$set.email).toBe('test@example.com')
        expect((response.execResult as any).properties.$set_once.sensitive).toBe('should-stay')
    })

    it('should filter properties from $set_once when enabled', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    sensitive: 'remove-me',
                    $set: {
                        sensitive: 'should-stay',
                        email: 'test@example.com',
                    },
                    $set_once: {
                        sensitive: 'should-be-removed',
                        username: 'test-user',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: 'sensitive',
                includeSetProperties: false,
                includeSetOnceProperties: true,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.sensitive).toBeUndefined()
        expect((response.execResult as any).properties.$set.sensitive).toBe('should-stay')
        expect((response.execResult as any).properties.$set_once.sensitive).toBeUndefined()
        expect((response.execResult as any).properties.$set_once.username).toBe('test-user')
    })

    it('should handle property names with special characters', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    '$feature/flag': true,
                    '$experiment/variant': 'control',
                    $geoip_city_name: 'London',
                    'app/version': '1.2.3',
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$feature/flag,$geoip_city_name',
                includeSetProperties: false,
                includeSetOnceProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties['$feature/flag']).toBeUndefined()
        expect((response.execResult as any).properties['$experiment/variant']).toBe('control')
        expect((response.execResult as any).properties.$geoip_city_name).toBeUndefined()
        expect((response.execResult as any).properties['app/version']).toBe('1.2.3')
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })

    it('should handle case-insensitive property matching', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $IP: 'should-stay',
                    ip: 'should-stay',
                    $set: {
                        IP: 'should-stay',
                        $IP: 'should-stay',
                        $ip: 'should-be-removed',
                    },
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$ip',
                includeSetProperties: true,
                includeSetOnceProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.$IP).toBe('should-stay')
        expect((response.execResult as any).properties.ip).toBe('should-stay')
        expect((response.execResult as any).properties.$set.IP).toBe('should-stay')
        expect((response.execResult as any).properties.$set.$IP).toBe('should-stay')
        expect((response.execResult as any).properties.$set.$ip).toBeUndefined()
        expect((response.execResult as any).properties.safe_property).toBe('keep-me')
    })

    it('should handle empty propertiesToFilter', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    $ip: '127.0.0.1',
                    $set: {
                        $ip: 'keep-me',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '',
                includeSetProperties: true,
                includeSetOnceProperties: true,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).distinct_id).toBe('user123')
        expect((response.execResult as any).properties.$ip).toBe('127.0.0.1')
        expect((response.execResult as any).properties.$set.$ip).toBe('keep-me')
    })

    it('should handle exact property name matching', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: 'should-be-removed',
                    $IP: 'should-stay',
                    ip: 'should-stay',
                    IP: 'should-stay',
                    $set: {
                        $ip: 'should-be-removed',
                        $IP: 'should-stay',
                        ip: 'should-stay',
                        IP: 'should-stay',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$ip',
                includeSetProperties: true,
                includeSetOnceProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as any).properties.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$IP).toBe('should-stay')
        expect((response.execResult as any).properties.ip).toBe('should-stay')
        expect((response.execResult as any).properties.IP).toBe('should-stay')
        expect((response.execResult as any).properties.$set.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$set.$IP).toBe('should-stay')
        expect((response.execResult as any).properties.$set.ip).toBe('should-stay')
        expect((response.execResult as any).properties.$set.IP).toBe('should-stay')
    })

    it('should handle nested properties in $set and $set_once', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: 'should-be-removed',
                    nested: {
                        $ip: 'should-be-removed',
                        other: 'should-stay',
                    },
                    $set: {
                        user: {
                            profile: {
                                $ip: 'should-be-removed-if-set-enabled',
                                email: 'keep@example.com',
                            },
                            settings: {
                                $ip: 'should-be-removed-if-set-enabled',
                                theme: 'dark',
                            },
                        },
                    },
                    $set_once: {
                        device: {
                            info: {
                                $ip: 'should-be-removed-if-set-once-enabled',
                                id: 'device-123',
                            },
                        },
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToFilter: '$ip',
                includeSetProperties: true,
                includeSetOnceProperties: true,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        // Check top-level and nested properties
        expect((response.execResult as any).properties.$ip).toBeUndefined()
        expect((response.execResult as any).properties.nested.$ip).toBeUndefined()
        expect((response.execResult as any).properties.nested.other).toBe('should-stay')

        // Check deeply nested $set properties
        expect((response.execResult as any).properties.$set.user.profile.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$set.user.profile.email).toBe('keep@example.com')
        expect((response.execResult as any).properties.$set.user.settings.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$set.user.settings.theme).toBe('dark')

        // Check deeply nested $set_once properties
        expect((response.execResult as any).properties.$set_once.device.info.$ip).toBeUndefined()
        expect((response.execResult as any).properties.$set_once.device.info.id).toBe('device-123')
    })
})
