import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './microsoft_teams.template'

describe('microsoft teams template', () => {
    const tester = new TemplateTester(template)

    const TEAM_ID = '4d1d7b4a-9a8e-4c2b-8f2e-3c1d2a6b9e10'
    const CHANNEL_ID = '19:abc123@thread.tacv2'
    const CHANNEL_URL = `https://graph.microsoft.com/v1.0/teams/${TEAM_ID}/channels/${encodeURIComponent(CHANNEL_ID)}/messages`

    const commonInputs = {
        microsoft_teams: { access_token: 'graph-token' },
        team: TEAM_ID,
        channel: CHANNEL_ID,
        message: '<b>Hello</b>',
        content_type: 'html',
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it.each([
        ['starts a new thread', undefined, CHANNEL_URL, { message_id: 'msg-new', reply_id: null }],
        [
            'replies in an existing thread',
            'root-1',
            `${CHANNEL_URL}/root-1/replies`,
            { message_id: 'root-1', reply_id: 'msg-new' },
        ],
    ])('%s', async (_name, replyToMessageId, expectedUrl, expectedIds) => {
        const response = await tester.invoke({ ...commonInputs, reply_to_message_id: replyToMessageId })

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchObject({
            url: expectedUrl,
            method: 'POST',
            headers: { Authorization: 'Bearer graph-token', 'Content-Type': 'application/json' },
        })
        expect(parseJSON((response.invocation.queueParameters as any).body)).toEqual({
            body: { contentType: 'html', content: '<b>Hello</b>' },
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: { id: 'msg-new', webUrl: 'https://teams.microsoft.com/l/message/x' },
        })

        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.execResult).toEqual({ ...expectedIds, web_url: 'https://teams.microsoft.com/l/message/x' })
    })

    it('fails the invocation when Graph rejects the message', async () => {
        const response = await tester.invoke(commonInputs)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { error: { code: 'Forbidden' } },
        })

        expect(fetchResponse.error).toMatch(/Failed to post message to Microsoft Teams: 403/)
    })
})
