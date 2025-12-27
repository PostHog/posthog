import { DateTime } from 'luxon'

import { parseJSON } from '../../../../utils/json-parse'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './firebase_push.template'

describe('firebase push template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function with required fields', async () => {
        const response = await tester.invoke(
            {
                firebase_account: {
                    project_id: 'posthog-test',
                    access_token: 'test-access-token',
                },
                fcm_token: 'device-fcm-token-12345',
                title: 'Test Notification',
                body: 'Hello from PostHog!',
            },
            {
                event: {
                    event: 'test-event',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"message":{"token":"device-fcm-token-12345","notification":{"title":"Test Notification","body":"Hello from PostHog!"},"data":{}}}",
              "headers": {
                "Authorization": "Bearer test-access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://fcm.googleapis.com/v1/projects/posthog-test/messages:send",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { name: 'projects/posthog-test/messages/123456' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should include custom data payload when provided', async () => {
        const response = await tester.invoke(
            {
                firebase_account: {
                    project_id: 'posthog-test',
                    access_token: 'test-access-token',
                },
                fcm_token: 'device-fcm-token-12345',
                title: 'Test Notification',
                body: 'Hello!',
                data: {
                    deep_link: '/products/123',
                    action: 'view_product',
                },
            },
            {
                event: {
                    event: 'purchase',
                },
            }
        )

        expect(response.error).toBeUndefined()
        const queueParams = response.invocation.queueParameters as { body: string }
        const body = parseJSON(queueParams.body)
        expect(body.message.data).toEqual({
            deep_link: '/products/123',
            action: 'view_product',
        })
    })

    it('should throw error when fcm_token is missing', async () => {
        const response = await tester.invoke(
            {
                firebase_account: {
                    project_id: 'posthog-test',
                    access_token: 'test-access-token',
                },
                fcm_token: '',
                title: 'Test Notification',
            },
            {
                event: {
                    event: 'test-event',
                },
            }
        )

        expect(response.finished).toBe(true)
        expect(response.error).toContain('FCM token is required')
    })

    it('should throw error when title is missing', async () => {
        const response = await tester.invoke(
            {
                firebase_account: {
                    project_id: 'posthog-test',
                    access_token: 'test-access-token',
                },
                fcm_token: 'device-fcm-token-12345',
                title: '',
            },
            {
                event: {
                    event: 'test-event',
                },
            }
        )

        expect(response.finished).toBe(true)
        expect(response.error).toContain('Notification title is required')
    })

    it('should handle FCM API error response', async () => {
        const response = await tester.invoke(
            {
                firebase_account: {
                    project_id: 'posthog-test',
                    access_token: 'test-access-token',
                },
                fcm_token: 'invalid-token',
                title: 'Test',
                body: 'Test',
            },
            {
                event: {
                    event: 'test-event',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: {
                error: {
                    code: 400,
                    message: 'The registration token is not a valid FCM registration token',
                    status: 'INVALID_ARGUMENT',
                },
            },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toContain('Failed to send push notification via FCM')
    })

    it('should use liquid templating for title and body', async () => {
        const response = await tester.invoke(
            {
                firebase_account: {
                    project_id: 'posthog-test',
                    access_token: 'test-access-token',
                },
                fcm_token: 'device-token',
                title: 'Hello {{ person.properties.name }}',
                body: 'You triggered {{ event.event }}',
            },
            {
                event: {
                    event: 'page_view',
                },
                person: {
                    properties: {
                        name: 'John',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        const queueParams = response.invocation.queueParameters as { body: string }
        const body = parseJSON(queueParams.body)
        expect(body.message.notification.title).toBe('Hello John')
        expect(body.message.notification.body).toBe('You triggered page_view')
    })
})
