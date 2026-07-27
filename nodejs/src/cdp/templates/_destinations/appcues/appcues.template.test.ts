import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './appcues.template'

describe('appcues template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const baseInputs = {
        accountId: '12345',
        apiKey: 'test_api_key',
        apiSecret: 'test_api_secret',
        region: 'US',
        userId: 'user-123',
        include_all_properties: false,
    }

    describe('track calls', () => {
        it('sends a track event to the events endpoint', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'Product Viewed',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: { product_id: 'widget-123' },
                    },
                },
                {
                    eventName: 'Product Viewed',
                    attributes: { product_id: 'widget-123' },
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(false)
            const queueParams = response.invocation.queueParameters as any
            expect(queueParams.url).toBe('https://api.appcues.com/v2/accounts/12345/users/user-123/events')
            expect(queueParams.method).toBe('POST')

            const decoded = Buffer.from(queueParams.headers.Authorization.replace('Basic ', ''), 'base64').toString()
            expect(decoded).toBe('test_api_key:test_api_secret')

            const body = parseJSON(queueParams.body)
            expect(body.name).toBe('Product Viewed')
            expect(body.timestamp).toBe('2024-01-01T00:00:00Z')
            expect(body.attributes).toEqual({ product_id: 'widget-123' })
        })

        it('includes group_id when provided', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                baseInputs,
                {
                    event: {
                        event: 'Plan Upgraded',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    eventName: 'Plan Upgraded',
                    groupId: 'company-99',
                    attributes: {},
                }
            )

            const body = parseJSON((response.invocation.queueParameters as any).body)
            expect(body.group_id).toBe('company-99')
        })

        it('uses the EU endpoint when region is EU', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                { ...baseInputs, region: 'EU' },
                {
                    event: {
                        event: 'Product Viewed',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    eventName: 'Product Viewed',
                    attributes: {},
                }
            )

            expect((response.invocation.queueParameters as any).url).toBe(
                'https://api.eu.appcues.com/v2/accounts/12345/users/user-123/events'
            )
        })
    })

    describe('identify calls', () => {
        it('sends a profile update to the profile endpoint', async () => {
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
                        properties: { email: 'test@example.com', first_name: 'Jane' },
                    },
                },
                {
                    profileProperties: { email: 'test@example.com', first_name: 'Jane' },
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(false)
            const queueParams = response.invocation.queueParameters as any
            expect(queueParams.url).toBe('https://api.appcues.com/v2/accounts/12345/users/user-123/profile')
            expect(queueParams.method).toBe('PATCH')

            const body = parseJSON(queueParams.body)
            expect(body).toEqual({ email: 'test@example.com', first_name: 'Jane' })
        })

        it('skips when there are no profile properties to send', async () => {
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
                    person: { properties: {} },
                },
                {
                    profileProperties: {},
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.invocation.queueParameters).toBeUndefined()
        })
    })

    describe('user id handling', () => {
        it('skips when user ID is empty', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                { ...baseInputs, userId: '' },
                {
                    event: {
                        event: 'Product Viewed',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                },
                {
                    eventName: 'Product Viewed',
                    attributes: {},
                }
            )

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
            expect(response.invocation.queueParameters).toBeUndefined()
        })
    })

    describe('include all properties', () => {
        it('merges non-$ event properties into track attributes', async () => {
            const response = await tester.invokeMapping(
                'Track Calls',
                { ...baseInputs, include_all_properties: true },
                {
                    event: {
                        event: 'Product Viewed',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: { product_id: 'widget-123', $browser: 'Chrome' },
                    },
                },
                {
                    eventName: 'Product Viewed',
                    attributes: { source: 'web' },
                }
            )

            const body = parseJSON((response.invocation.queueParameters as any).body)
            expect(body.attributes).toEqual({ product_id: 'widget-123', source: 'web' })
            expect(body.attributes.$browser).toBeUndefined()
        })

        it('merges non-$ person properties into the identify profile', async () => {
            const response = await tester.invokeMapping(
                'Identify Calls',
                { ...baseInputs, include_all_properties: true },
                {
                    event: {
                        event: '$identify',
                        distinct_id: 'user-123',
                        timestamp: '2024-01-01T00:00:00Z',
                        properties: {},
                    },
                    person: {
                        properties: { email: 'test@example.com', company: 'Acme', $initial_referrer: 'google' },
                    },
                },
                {
                    profileProperties: { plan: 'enterprise' },
                }
            )

            const body = parseJSON((response.invocation.queueParameters as any).body)
            expect(body).toEqual({ email: 'test@example.com', company: 'Acme', plan: 'enterprise' })
            expect(body.$initial_referrer).toBeUndefined()
        })
    })

    describe('error handling', () => {
        const cases = [
            {
                mapping: 'Track Calls',
                event: { event: 'Product Viewed', properties: {} },
                mappingInputs: { eventName: 'Product Viewed', attributes: {} },
            },
            {
                mapping: 'Identify Calls',
                event: { event: '$identify', properties: {} },
                mappingInputs: { profileProperties: { email: 'test@example.com' } },
            },
        ]

        it.each(cases)('throws on API failure for $mapping', async ({ mapping, event, mappingInputs }) => {
            let response = await tester.invokeMapping(
                mapping,
                baseInputs,
                {
                    event: { ...event, distinct_id: 'user-123', timestamp: '2024-01-01T00:00:00Z' },
                    person: { properties: { email: 'test@example.com' } },
                },
                mappingInputs
            )

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 401,
                body: { error: 'Unauthorized' },
            })

            expect(response.error).toMatch(/Error from Appcues API \(status 401\)/)
        })

        it.each(cases)('finishes on a successful response for $mapping', async ({ mapping, event, mappingInputs }) => {
            let response = await tester.invokeMapping(
                mapping,
                baseInputs,
                {
                    event: { ...event, distinct_id: 'user-123', timestamp: '2024-01-01T00:00:00Z' },
                    person: { properties: { email: 'test@example.com' } },
                },
                mappingInputs
            )

            response = await tester.invokeFetchResponse(response.invocation, {
                status: 200,
                body: { status: 200, title: 'OK' },
            })

            expect(response.error).toBeUndefined()
            expect(response.finished).toBe(true)
        })
    })
})
