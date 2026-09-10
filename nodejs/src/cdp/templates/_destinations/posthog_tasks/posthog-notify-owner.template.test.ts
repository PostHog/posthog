import jwt from 'jsonwebtoken'

import { getAsyncFunctionHandler } from '~/cdp/async-function-registry'
import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-notify-owner.template'

describe('posthog notify owner template', () => {
    const tester = new TemplateTester(template)
    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000002' }, actionId: 'action_1' }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('stages an authenticated notify request with a step-scoped idempotency key', async () => {
        const response = await tester.invoke(
            {
                title: 'Nightly triage finished',
                body: '3 issues triaged',
                task_id: '0198c9f1-aaaa-0000-0000-000000000009',
            },
            undefined,
            workflowOptions
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        const params = response.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
        expect(params.method).toBe('POST')
        expect(params.url).toMatch(/\/api\/projects\/1\/workflow_notifications\/$/)
        expect(parseJSON(params.body!)).toEqual({
            title: 'Nightly triage finished',
            body: '3 issues triaged',
            task_id: '0198c9f1-aaaa-0000-0000-000000000009',
            idempotency_key: `${response.invocation.id}:action_1:0`,
        })

        const token = (params.headers?.['Authorization'] ?? '').replace('Bearer ', '')
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(token, 'local-dev-workflow-notify-jwt', {
            audience: 'posthog:workflows:notify',
            algorithms: ['HS256'],
        }) as jwt.JwtPayload
        expect(claims.team_id).toBe(1)
        expect(claims.hog_flow_id).toBe(workflowOptions.hogFlow.id)
    })

    it('mocks as a success in a test run without sending anything', () => {
        const logs: any[] = []
        const result = getAsyncFunctionHandler('postHogNotifyOwner')!.mock([{ title: 'Nightly triage finished' }], logs)

        // The hog code fails the step on status >= 400, so the mock must read as delivered.
        expect(result).toEqual({ status: 202, body: {} })
        expect(logs.map((log) => log.message)).toEqual([
            "Async function 'postHogNotifyOwner' was mocked. No notification was sent. Arguments:",
            expect.stringContaining('"title": "Nightly triage finished"'),
        ])
    })

    it('fails the step when the title is empty', async () => {
        const response = await tester.invoke({ title: '', body: 'x' }, undefined, workflowOptions)

        expect(response.error).toContain('Title is required')
    })
})
