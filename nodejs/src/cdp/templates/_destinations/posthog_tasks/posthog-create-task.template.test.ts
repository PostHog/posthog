import '~/tests/helpers/mocks/date.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import jwt from 'jsonwebtoken'

import { parseJSON } from '~/common/utils/json-parse'

import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../../index'
import { TemplateTester } from '../../test/test-helpers'

const template = NATIVE_HOG_FUNCTIONS_BY_ID['native-posthog-create-task']

const respondWith = (status: number, body: Record<string, any>) =>
    mockFetch.mockResolvedValue({
        status,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
        headers: { 'content-type': 'application/json' },
        dump: () => Promise.resolve(),
    })

const lastRequest = () => {
    const [url, options] = mockFetch.mock.calls[mockFetch.mock.calls.length - 1]
    return { url, options, body: parseJSON(options.body) }
}

describe(`${template.name} template`, () => {
    const tester = new TemplateTester({ ...template, code: '', code_language: 'javascript' })

    beforeEach(async () => {
        await tester.beforeEach()
        respondWith(201, { id: 'task-1', title: 'Look into the alert' })
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('posts the prompt and the workflow id to the tasks endpoint', async () => {
        await tester.invoke({ prompt: 'look into the alert' })

        const { url, body } = lastRequest()
        expect(url).toContain('/workflow_tasks/')
        expect(body.prompt).toBe('look into the alert')
        expect(body.hog_flow_id).toBeTruthy()
    })

    it('authenticates with a scoped token pinned to the team and workflow', async () => {
        await tester.invoke({ prompt: 'look into the alert' })

        const { options, body } = lastRequest()
        const token = options.headers.Authorization.replace('Bearer ', '')
        const claims = jwt.decode(token) as Record<string, any>

        expect(claims.aud).toBe('posthog:tasks:create')
        expect(claims.hog_flow_id).toBe(body.hog_flow_id)
        expect(claims.team_id).toBeDefined()
        expect(claims.exp).toBeDefined()
    })

    it('sends the Slack context when a channel and thread are configured', async () => {
        await tester.invoke({
            prompt: 'look into the alert',
            slack_channel: 'C0ALERTS',
            slack_thread_ts: '1700000000.000100',
            slack_user_id: 'U123',
        })

        expect(lastRequest().body.context).toEqual({
            type: 'slack',
            channel: 'C0ALERTS',
            thread_ts: '1700000000.000100',
            slack_user_id: 'U123',
            slack_team_id: '',
        })
    })

    it('omits the context when there is no thread to reply into', async () => {
        await tester.invoke({ prompt: 'look into the alert', slack_channel: 'C0ALERTS' })

        expect(lastRequest().body.context).toBeUndefined()
    })

    it('sends no context from a trigger that has no Slack properties', async () => {
        // The Slack inputs default to {event.properties.channel} and {event.properties.ts}, which
        // resolve to nothing on any other trigger. A truthy leftover would bind a bogus thread.
        await tester.invoke({ prompt: 'do a thing' })

        const { body } = lastRequest()
        expect(body.context).toBeUndefined()
        expect(body.prompt).toBe('do a thing')
    })

    it('treats an at-capacity workflow as skipped rather than failed', async () => {
        respondWith(409, { detail: 'Workflow already has 5 tasks in flight (limit 5).' })

        const response = await tester.invoke({ prompt: 'look into the alert' })

        expect(response.error).toBeUndefined()
    })

    it('fails the step when the endpoint rejects the request', async () => {
        respondWith(422, { detail: 'Workflow has no owner who can run tasks.' })

        const response = await tester.invoke({ prompt: 'look into the alert' })

        expect(String(response.error)).toContain('Workflow has no owner')
    })
})
