import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './accoil.template'

describe('accoil template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    const baseInputs = {
        apiKey: 'test_api_key_123',
        timestamp: '{event.timestamp}',
    }

    describe('event type routing', () => {
        it('should handle $identify events as identify calls', async () => {
            const response = await tester.invokeMapping(
                'Identify Calls',
                baseInputs,
                {
                    event: {
                        event: '$identify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $set: {
                                email: 'test@example.com',
                                name: 'John Doe',
                            },
                        },
                    },
                    person: {
                        properties: {
                            email: 'test@example.com',
                            name: 'John Doe',
                            role: 'admin',
                        },
                    },
                },
                {
                    userId: 'user-123',
                    email: 'test@example.com',
                    user_name: 'John Doe',
                    role: 'admin',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toEqual(false)
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()

            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('identify')
            expect(body.userId).toBe('user-123')
            expect(body.traits).toEqual({
                email: 'test@example.com',
                name: 'John Doe',
                role: 'admin',
            })
        })

        it('should handle $set events as identify calls', async () => {
            const response = await tester.invokeMapping(
                'Identify Calls',
                baseInputs,
                {
                    event: {
                        event: '$set',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $set: {
                                email: 'test@example.com',
                                name: 'John Updated',
                            },
                        },
                    },
                    person: {
                        properties: {
                            email: 'test@example.com',
                            name: 'John Updated',
                        },
                    },
                },
                {
                    email: 'test@example.com',
                    user_name: 'John Updated',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('identify')
            expect(body.userId).toBe('user-123')
            expect(body.traits).toEqual({
                email: 'test@example.com',
                name: 'John Updated',
            })
        })

        it('should handle $pageview events as page calls', async () => {
            const response = await tester.invokeMapping(
                'Page Calls',
                baseInputs,
                {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $current_url: 'https://example.com',
                            title: 'Homepage',
                        },
                    },
                },
                {
                    userId: 'user-123',
                    name: 'Homepage',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('page')
            expect(body.name).toBe('Homepage')
        })

        it('should handle $screen events as screen calls', async () => {
            const response = await tester.invokeMapping(
                'Screen Calls',
                baseInputs,
                {
                    event: {
                        event: '$screen',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $screen_name: 'ProductScreen',
                        },
                    },
                },
                {
                    name: 'ProductScreen',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('screen')
            expect(body.name).toBe('ProductScreen')
        })

        it('should handle $groupidentify events as group calls', async () => {
            const response = await tester.invokeMapping(
                'Group Calls',
                baseInputs,
                {
                    event: {
                        event: '$groupidentify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $group_type: 'company',
                            $group_key: 'company-123',
                            $group_set: {
                                name: 'Acme Corp',
                                plan: 'enterprise',
                                mrr: 50000,
                            },
                        },
                    },
                },
                {
                    userId: 'user-123',
                    anonymousId: 'anon-123',
                    groupId: 'company-123',
                    group_name: 'Acme Corp',
                    group_plan: 'enterprise',
                    group_mrr: '50000',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('group')
            expect(body.groupId).toBe('company-123')
            expect(body.traits).toEqual({
                name: 'Acme Corp',
                plan: 'enterprise',
                mrr: 50000,
            })
        })

        it('should handle custom events as track calls', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'Product Viewed',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            product_id: 'widget-123',
                            price: 29.99,
                        },
                    },
                },
                {
                    userId: 'user-123',
                    event: 'Product Viewed',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('track')
            expect(body.event).toBe('Product Viewed')
        })
    })

    describe('mapping behavior', () => {
        // Note: HogQL filters are tested in production but not in the test environment
        // due to test helper limitations that bypass the filtering logic

        it('should allow custom events in Track Calls mapping when explicitly enabled', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'custom_button_click',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    event: 'custom_button_click',
                }
            )

            expect(response.finished).toBe(false)
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('track')
            expect(body.event).toBe('custom_button_click')
        })
    })

    describe('system event filtering', () => {
        it('should skip internal PostHog events not in whitelist', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: '$web_vitals',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {}
            )

            // The function should finish early and not create any queue parameters
            expect(response.finished).toBe(true)
            expect(response.invocation.queueParameters).toBeUndefined()
        })

        it('should process custom events like spinner_unloaded as track calls', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'spinner_unloaded',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    event: 'spinner_unloaded',
                }
            )

            // This is a custom event (no $ prefix) so it should process as a track call
            expect(response.finished).toBe(false)
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('track')
            expect(body.event).toBe('spinner_unloaded')
        })

        it('should allow whitelisted system events', async () => {
            const response = await tester.invokeMapping(
                'Page Calls',
                baseInputs,
                {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {}
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
        })
    })

    describe('endpoint routing', () => {
        it('should use production endpoint for normal API keys', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                {
                    ...baseInputs,
                    apiKey: 'prod_api_key_123',
                },
                {
                    event: {
                        event: 'test_event',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    event: 'test_event',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            expect((response.invocation!.queueParameters as any).url).toBe('https://in.accoil.com/segment')
        })

        it('should use staging endpoint and strip prefix for staging API keys', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                {
                    ...baseInputs,
                    apiKey: 'stg_api_key_123',
                },
                {
                    event: {
                        event: 'test_event',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    event: 'test_event',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            expect((response.invocation!.queueParameters as any).url).toBe('https://instaging.accoil.com/segment')

            // Check that the API key prefix was stripped in the Authorization header
            const authHeader = (response.invocation!.queueParameters as any).headers.Authorization
            const credentials = authHeader.replace('Basic ', '')
            const decoded = Buffer.from(credentials, 'base64').toString()
            expect(decoded).toBe('api_key_123:') // Should not include 'stg_' prefix
        })
    })

    describe('trait mapping', () => {
        it('should include manually configured user traits', async () => {
            const response = await tester.invokeMapping(
                'Identify Calls',
                baseInputs,
                {
                    event: {
                        event: '$identify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                    person: {
                        properties: {
                            email: 'manual@example.com',
                            company: 'Acme Corp',
                            department: 'Engineering',
                        },
                    },
                },
                {
                    email: 'manual@example.com',
                    user_name: 'John Doe',
                    role: 'admin',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.traits).toEqual({
                email: 'manual@example.com',
                name: 'John Doe',
                role: 'admin',
            })
        })

        it('should include manually configured group traits', async () => {
            const response = await tester.invokeMapping(
                'Group Calls',
                baseInputs,
                {
                    event: {
                        event: '$groupidentify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $group_type: 'company',
                            $group_key: 'company-123',
                            $group_set: {
                                name: 'Manual Name',
                                industry: 'Technology',
                                size: 'Large',
                            },
                        },
                    },
                },
                {
                    groupId: 'company-123',
                    group_name: 'Manual Name',
                    group_plan: 'enterprise',
                    group_status: 'active',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.traits).toEqual({
                name: 'Manual Name',
                plan: 'enterprise',
                status: 'active',
            })
        })
    })

    describe('error handling', () => {
        it('should throw error on API failure', async () => {
            let response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'test_event',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    event: 'test_event',
                }
            )

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 400,
                body: { error: 'Invalid API key' },
            })

            expect(response.error).toMatch(/Error from Accoil \(status 400\)/)
        })

        it('should handle successful API response', async () => {
            let response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'test_event',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    event: 'test_event',
                }
            )

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 200,
                body: { success: true },
            })

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
        })
    })

    describe('trait filtering', () => {
        it('should filter out traits with geoip in the key name', async () => {
            const response = await tester.invokeMapping(
                'Identify Calls',
                baseInputs,
                {
                    event: {
                        event: '$identify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                    person: {
                        properties: {
                            email: 'test@example.com',
                            name: 'John Doe',
                            geoip_country: 'US',
                            $geoip_city_name: 'San Francisco',
                            company: 'Acme Corp',
                        },
                    },
                },
                {
                    email: 'test@example.com',
                    user_name: 'John Doe',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.traits).toEqual({
                email: 'test@example.com',
                name: 'John Doe',
                // geoip_country and $geoip_city_name should be filtered out
                // company should remain since it doesn't contain 'geoip' or 'ip'
            })
            expect(body.traits.geoip_country).toBeUndefined()
            expect(body.traits.$geoip_city_name).toBeUndefined()
        })

        it('should filter out traits with ip in the key name', async () => {
            const response = await tester.invokeMapping(
                'Group Calls',
                baseInputs,
                {
                    event: {
                        event: '$groupidentify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $group_type: 'company',
                            $group_key: 'company-123',
                            $group_set: {
                                name: 'Acme Corp',
                                plan: 'enterprise',
                                client_ip: '192.168.1.1',
                                $ip_address: '10.0.0.1',
                                industry: 'Technology',
                            },
                        },
                    },
                },
                {
                    groupId: 'company-123',
                    group_name: 'Acme Corp',
                    group_plan: 'enterprise',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.traits).toEqual({
                name: 'Acme Corp',
                plan: 'enterprise',
                // client_ip and $ip_address should be filtered out
                // industry should remain since it doesn't contain 'geoip' or 'ip'
            })
            expect(body.traits.client_ip).toBeUndefined()
            expect(body.traits.$ip_address).toBeUndefined()
        })
    })

    describe('type conversions', () => {
        it('should convert MRR to float', async () => {
            const response = await tester.invokeMapping(
                'Group Calls',
                baseInputs,
                {
                    event: {
                        event: '$groupidentify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $group_type: 'company',
                            $group_key: 'company-123',
                            $group_set: {
                                mrr: '50000.75',
                            },
                        },
                    },
                },
                {
                    groupId: 'company-123',
                    group_mrr: '50000.75',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.traits.mrr).toBe(50000.75)
            expect(typeof body.traits.mrr).toBe('number')
        })
    })

    describe('empty page name handling', () => {
        it('should return early for page events with empty name', async () => {
            const response = await tester.invokeMapping(
                'Page Calls',
                baseInputs,
                {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            // No title or pathname properties, so name will be empty
                        },
                    },
                },
                {
                    name: '', // Empty page name
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.invocation.queueParameters).toBeUndefined() // No HTTP request should be made
        })

        it('should return early for page events with null input name', async () => {
            const response = await tester.invokeMapping(
                'Page Calls',
                baseInputs,
                {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            $current_url: 'http://localhost:8010/project/1/functions/new/template-accoil',
                            // No title or $pathname properties, so default template evaluates to null
                        },
                    },
                },
                {
                    name: null, // Template evaluates to null when properties are missing
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.invocation.queueParameters).toBeUndefined() // No HTTP request should be made
        })

        it('should return early for screen events with empty name', async () => {
            const response = await tester.invokeMapping(
                'Screen Calls',
                baseInputs,
                {
                    event: {
                        event: '$screen',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    name: '', // Empty screen name
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.invocation.queueParameters).toBeUndefined() // No HTTP request should be made
        })

        it('should proceed with page events when name is provided', async () => {
            const response = await tester.invokeMapping(
                'Page Calls',
                baseInputs,
                {
                    event: {
                        event: '$pageview',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {
                            title: 'Test Page',
                        },
                    },
                },
                {
                    name: 'Test Page',
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.invocation).toBeDefined()
            expect(response.invocation.queueParameters).toBeDefined()
            const body = parseJSON((response.invocation!.queueParameters as any).body)
            expect(body.type).toBe('page')
            expect(body.name).toBe('Test Page')
        })
    })
})
