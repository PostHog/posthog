import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './telegram.template'

describe('telegram template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should send a plain text message with only the required fields', async () => {
        const response = await tester.invoke(
            {
                bot_token: '123456:test-token',
                chat_id: '{person.properties.telegram_chat_id}',
            },
            {
                event: { event: 'signed_up' },
                person: { name: 'Max', properties: { telegram_chat_id: '-1001234567890' } },
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
        expect(queueParams.url).toBe('https://api.telegram.org/bot123456:test-token/sendMessage')
        expect(queueParams.method).toBe('POST')
        expect(queueParams.headers).toEqual({ 'Content-Type': 'application/json' })
        expect(parseJSON(queueParams.body)).toEqual({
            chat_id: '-1001234567890',
            text: 'Max triggered event: signed_up',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { ok: true, result: { message_id: 1 } },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should send the optional fields when they are set', async () => {
        const response = await tester.invoke(
            {
                bot_token: '123456:test-token',
                chat_id: '@mychannel',
                text: '<b>{event.event}</b>',
                parse_mode: 'HTML',
                message_thread_id: '42',
                disable_notification: true,
                disable_link_preview: true,
            },
            { event: { event: 'signed_up' } }
        )

        expect(response.error).toBeUndefined()
        expect(parseJSON((response.invocation.queueParameters as { body: string }).body)).toEqual({
            chat_id: '@mychannel',
            text: '<b>signed_up</b>',
            parse_mode: 'HTML',
            message_thread_id: 42,
            disable_notification: true,
            link_preview_options: { is_disabled: true },
        })
    })

    it.each([
        {
            name: 'chat ID is empty',
            inputs: { bot_token: '123456:test-token', chat_id: '', text: 'Hello' },
            expectedError: /Chat ID is required/,
        },
        {
            name: 'message text is empty',
            inputs: { bot_token: '123456:test-token', chat_id: '123', text: '' },
            expectedError: /Message text is required/,
        },
        {
            name: 'topic ID is not a number',
            inputs: { bot_token: '123456:test-token', chat_id: '123', text: 'Hello', message_thread_id: 'general' },
            expectedError: /Topic ID must be a number/,
        },
    ])('should error when $name', async ({ inputs, expectedError }) => {
        const response = await tester.invoke(inputs, { event: { event: 'signed_up' } })

        expect(response.error).toMatch(expectedError)
    })

    it.each([
        { name: 'a non-200 status', status: 400, body: { ok: false, description: 'Bad Request: chat not found' } },
        { name: 'ok set to false', status: 200, body: { ok: false, description: 'Forbidden: bot was blocked' } },
    ])('should throw on $name', async ({ status, body }) => {
        const response = await tester.invoke(
            { bot_token: '123456:test-token', chat_id: '123', text: 'Hello' },
            { event: { event: 'signed_up' } }
        )

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status, body })

        expect(fetchResponse.error).toMatch(`Failed to send Telegram message: ${status}: ${body.description}`)
    })
})
