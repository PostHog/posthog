import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './retain.template'

describe('retain template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    const baseInputs = {
        writeKey: 'rk-test-write-key',
    }

    it('should forward a custom event with the person attached', async () => {
        const response = await tester.invoke(baseInputs, {
            event: {
                uuid: 'event-uuid-1',
                event: 'report exported',
                distinct_id: 'user-123',
                timestamp: '2024-01-01T00:00:00Z',
                properties: {
                    format: 'csv',
                },
            },
            person: {
                properties: {
                    email: 'user@example.com',
                    name: 'Example User',
                },
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toBeDefined()

        const queueParameters = response.invocation.queueParameters as any
        expect(queueParameters.url).toBe('https://api.retain.so/sources/posthog')
        expect(queueParameters.method).toBe('POST')
        expect(queueParameters.headers).toEqual({
            Authorization: 'Basic rk-test-write-key',
            'Content-Type': 'application/json',
        })

        const body = parseJSON(queueParameters.body)
        expect(body).toEqual({
            event: {
                uuid: 'event-uuid-1',
                event: 'report exported',
                distinct_id: 'user-123',
                properties: {
                    format: 'csv',
                },
                timestamp: '2024-01-01T00:00:00Z',
            },
            person: {
                properties: {
                    email: 'user@example.com',
                    name: 'Example User',
                },
            },
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: { success: true, result: 'tracked' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it.each(['$identify', '$set', '$groupidentify'])('should forward %s identity events', async (eventName) => {
        const response = await tester.invoke(baseInputs, {
            event: {
                event: eventName,
                distinct_id: 'user-123',
                properties: {
                    $set: { email: 'user@example.com' },
                },
            },
            person: {
                properties: { email: 'user@example.com' },
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toBeDefined()

        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.event.event).toBe(eventName)
    })

    it.each(['$pageview', '$pageleave', '$autocapture', '$feature_flag_called', '$exception'])(
        'should skip PostHog internal event %s without making a request',
        async (eventName) => {
            const response = await tester.invoke(baseInputs, {
                event: {
                    event: eventName,
                    distinct_id: 'user-123',
                    properties: {},
                },
            })

            expect(response.error).toBeUndefined()
            expect(response.finished).toEqual(true)
            expect(response.invocation.queueParameters).toBeUndefined()
        }
    )

    it('should throw an error when Retain responds with an error status', async () => {
        const response = await tester.invoke(baseInputs, {
            event: {
                event: 'report exported',
                distinct_id: 'user-123',
                properties: {},
            },
        })

        expect(response.error).toBeUndefined()

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { message: 'Invalid write key' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from api.retain.so (status 401): {'message': 'Invalid write key'}"`
        )
    })
})
