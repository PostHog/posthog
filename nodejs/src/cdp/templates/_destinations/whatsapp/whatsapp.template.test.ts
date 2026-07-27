import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './whatsapp.template'

describe('whatsapp template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should send a text message', async () => {
        const response = await tester.invoke(
            {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                api_version: 'v21.0',
                message_type: 'text',
                message: 'Hello from PostHog',
            },
            {
                event: { event: 'event-name' },
                person: { properties: { phone: '+1234567893' } },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const queueParams = response.invocation.queueParameters as {
            url: string
            method: string
            headers: Record<string, string>
            body: string
        }
        expect(queueParams.url).toBe('https://graph.facebook.com/v21.0/987654321/messages')
        expect(queueParams.method).toBe('POST')
        expect(queueParams.headers).toEqual({
            Authorization: 'Bearer token_12345',
            'Content-Type': 'application/json',
        })
        expect(parseJSON(queueParams.body)).toEqual({
            messaging_product: 'whatsapp',
            recipient_type: 'individual',
            to: '+1234567893',
            type: 'text',
            text: { preview_url: false, body: 'Hello from PostHog' },
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { messages: [{ id: 'wamid.HBgL' }] },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should send a template message', async () => {
        const response = await tester.invoke(
            {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                api_version: 'v21.0',
                to_number: '+1234567893',
                message_type: 'template',
                template_name: 'hello_world',
                template_language: 'en_US',
            },
            {
                event: { event: 'event-name' },
                person: { properties: {} },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const queueParams = response.invocation.queueParameters as { url: string; body: string }
        expect(queueParams.url).toBe('https://graph.facebook.com/v21.0/987654321/messages')
        expect(parseJSON(queueParams.body)).toEqual({
            messaging_product: 'whatsapp',
            recipient_type: 'individual',
            to: '+1234567893',
            type: 'template',
            template: {
                name: 'hello_world',
                language: { code: 'en_US' },
            },
        })
    })

    it('should default the api version when blank', async () => {
        const response = await tester.invoke(
            {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                api_version: '',
                to_number: '+1234567893',
                message_type: 'text',
                message: 'Hello',
            },
            {
                event: { event: 'event-name' },
                person: { properties: {} },
            }
        )

        expect(response.error).toBeUndefined()
        expect((response.invocation.queueParameters as { url: string }).url).toEqual(
            'https://graph.facebook.com/v21.0/987654321/messages'
        )
    })

    it.each([
        {
            name: 'recipient phone is empty',
            inputs: {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                message_type: 'text',
                message: 'Hello',
                to_number: '',
            },
            expectedError: /Recipient phone number is required/,
        },
        {
            name: 'template name is empty for template messages',
            inputs: {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                to_number: '+1234567893',
                message_type: 'template',
                template_name: '',
            },
            expectedError: /Template name is required/,
        },
        {
            name: 'message body is empty for text messages',
            inputs: {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                to_number: '+1234567893',
                message_type: 'text',
                message: '',
            },
            expectedError: /Message body is required for text messages/,
        },
    ])('should error when $name', async ({ inputs, expectedError }) => {
        const response = await tester.invoke(inputs, {
            event: { event: 'event-name' },
            person: { properties: {} },
        })

        expect(response.error).toMatch(expectedError)
    })

    it('should throw on non-2xx response', async () => {
        const response = await tester.invoke(
            {
                access_token: 'token_12345',
                phone_number_id: '987654321',
                to_number: '+1234567893',
                message_type: 'text',
                message: 'Hello',
            },
            { event: { event: 'event-name' }, person: { properties: {} } }
        )

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { error: { message: 'invalid token' } },
        })

        expect(fetchResponse.error).toMatch(/Failed to send WhatsApp message/)
    })
})
