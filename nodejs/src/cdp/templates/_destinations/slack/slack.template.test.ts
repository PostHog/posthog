import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './slack.template'

describe('slack template', () => {
    const tester = new TemplateTester(template)

    const commonInputs = {
        slack_workspace: { access_token: 'xoxb-1234' },
        icon_emoji: ':hedgehog:',
        username: 'PostHog',
        channel: 'channel',
        blocks: [],
        text: 'hello',
    }

    // What the thread_ts input's description tells people to paste.
    const THREAD_TS_EXPRESSION = '{event.properties.thread_ts ?? event.properties.ts}'

    const slackMessage = (properties: Record<string, any> = {}): any => ({
        event: {
            event: '$slack_message_received',
            properties: { channel: 'C0ALERTS', ts: '1700000000.000100', thread_ts: null, ...properties },
        },
    })

    const bodyOf = (queueParameters: any): any => parseJSON(queueParameters.body)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should post a message', async () => {
        const response = await tester.invoke(commonInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchObject({
            url: 'https://slack.com/api/chat.postMessage',
            method: 'POST',
            headers: {
                Authorization: 'Bearer xoxb-1234',
                'Content-Type': 'application/json',
            },
        })
        expect(bodyOf(response.invocation.queueParameters)).toEqual({
            channel: 'channel',
            icon_emoji: ':hedgehog:',
            username: 'PostHog',
            blocks: [],
            text: 'hello',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { ok: true },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it.each([
        ['a top-level post, reply under that post', {}, '1700000000.000100'],
        ['a thread reply, reply in the same thread', { thread_ts: '1699999999.000000' }, '1699999999.000000'],
    ])('given %s', async (_name, properties, expected) => {
        const response = await tester.invoke(
            { ...commonInputs, thread_ts: THREAD_TS_EXPRESSION },
            slackMessage(properties)
        )

        expect(response.error).toBeUndefined()
        expect(bodyOf(response.invocation.queueParameters).thread_ts).toEqual(expected)
    })

    it.each([
        ['the input is unset', undefined],
        ['the input is empty', ''],
        // An event with no Slack timestamps resolves the expression to null, which must not be sent
        // either: Slack answers invalid_arguments instead of posting to the channel.
        ['the expression resolves to nothing', THREAD_TS_EXPRESSION],
    ])('should omit thread_ts when %s', async (_name, thread_ts) => {
        const response = await tester.invoke({ ...commonInputs, thread_ts })

        expect(response.error).toBeUndefined()
        expect(bodyOf(response.invocation.queueParameters)).not.toHaveProperty('thread_ts')
    })

    describe('Slack block limits', () => {
        const sectionBlock = (text: string): any => ({ type: 'section', text: { type: 'mrkdwn', text } })

        it('should shorten section text that is longer than 3000 characters', async () => {
            const response = await tester.invoke({ ...commonInputs, blocks: [sectionBlock('a'.repeat(3500))] })

            expect(response.error).toBeUndefined()
            expect(bodyOf(response.invocation.queueParameters).blocks).toEqual([
                sectionBlock(`${'a'.repeat(2999)}\u2026`),
            ])
        })

        it('should shorten a button label that is longer than 75 characters', async () => {
            const button = (text: string): any => ({
                type: 'button',
                url: 'https://example.com',
                text: { type: 'plain_text', text },
            })
            const blocks = [{ type: 'actions', elements: [button('b'.repeat(100))] }]

            const response = await tester.invoke({ ...commonInputs, blocks })

            expect(response.error).toBeUndefined()
            expect(bodyOf(response.invocation.queueParameters).blocks).toEqual([
                { type: 'actions', elements: [button(`${'b'.repeat(74)}\u2026`)] },
            ])
        })

        it('should send only the first 50 blocks', async () => {
            const blocks = Array.from({ length: 60 }, () => sectionBlock('block'))

            const response = await tester.invoke({ ...commonInputs, blocks })

            expect(response.error).toBeUndefined()
            expect(bodyOf(response.invocation.queueParameters).blocks).toEqual(blocks.slice(0, 50))
        })

        it('should keep blocks unset when there are none', async () => {
            const response = await tester.invoke({ ...commonInputs, blocks: undefined })

            expect(response.error).toBeUndefined()
            expect(bodyOf(response.invocation.queueParameters).blocks).toBeNull()
        })

        it('should leave blocks that are inside the limits alone', async () => {
            const blocks = [sectionBlock('short'), { type: 'divider' }]

            const response = await tester.invoke({ ...commonInputs, blocks })

            expect(response.error).toBeUndefined()
            expect(bodyOf(response.invocation.queueParameters).blocks).toEqual(blocks)
        })
    })

    it.each([
        ['a non-200 status', { status: 400, body: { ok: true } }, "Failed to post message to Slack: 400: {'ok': true}"],
        ['ok: false', { status: 200, body: { ok: false } }, "Failed to post message to Slack: 200: {'ok': false}"],
    ])('should throw on %s', async (_name, fetchResponse, expectedError) => {
        let response = await tester.invoke(commonInputs)
        response = await tester.invokeFetchResponse(response.invocation, fetchResponse)

        expect(response.error).toEqual(expectedError)
    })
})
