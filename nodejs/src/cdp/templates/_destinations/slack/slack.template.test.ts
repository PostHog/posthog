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

    // Both fields carry a default, so a connection without chat:write.customize would send them and
    // have Slack refuse the whole message. The granted scopes decide, not the saved value.
    it.each([
        ['the scope is granted', 'chat:write,chat:write.customize', true],
        ['the scope list has spaces', 'chat:write, chat:write.customize', true],
        // An install predating the recorded scope list keeps its customization, the same fail-open
        // the config UI applies.
        ['no scopes are recorded', '', true],
        ['the scope is absent', 'channels:read,groups:read,chat:write', false],
        // A prefix match on the granted list would wrongly accept this one.
        ['only the chat:write prefix is granted', 'chat:write', false],
    ])('given %s, sends the appearance fields: %s', async (_name, scope, expected) => {
        const response = await tester.invoke({
            ...commonInputs,
            slack_workspace: { access_token: 'xoxb-1234', scope },
        })

        expect(response.error).toBeUndefined()
        const body = bodyOf(response.invocation.queueParameters)
        expect(['icon_emoji' in body, 'username' in body]).toEqual([expected, expected])
    })

    // Clearing these has to keep the request inside chat:write, so a workspace that never granted
    // chat:write.customize has a way to make the destination work. The UI writes '' on clear, but an
    // API caller can leave the input unset or null, and neither may reach Slack either.
    it.each([
        ['icon_emoji', 'cleared in the UI', ''],
        ['icon_emoji', 'unset', undefined],
        ['icon_emoji', 'null', null],
        ['username', 'cleared in the UI', ''],
        ['username', 'unset', undefined],
        ['username', 'null', null],
    ])('should omit %s when it is %s', async (key, _name, value) => {
        const response = await tester.invoke({ ...commonInputs, [key]: value })

        expect(response.error).toBeUndefined()
        expect(bodyOf(response.invocation.queueParameters)).not.toHaveProperty(key)
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
