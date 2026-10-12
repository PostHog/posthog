import jwt from 'jsonwebtoken'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-replay-vision.template'

describe('posthog replay vision template', () => {
    const tester = new TemplateTester(template)

    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'action_1' }
    const analysis = { type: 'classifier', prompt: 'What did the user try to do?', tags: ['checkout', 'browse'] }
    const inputs = { session_id: 'session-1', analysis }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('stages an authenticated scan request keyed to this step', async () => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        expect(response.error).toBeUndefined()

        const params = response.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
        expect(params.url).toMatch(/\/api\/projects\/1\/workflow_vision_requests\/$/)
        expect(parseJSON(params.body!)).toEqual({
            session_id: 'session-1',
            setup: analysis,
            wait_for_session_end: true,
            idempotency_key: `${response.invocation.id}:action_1:0`,
        })

        const token = (params.headers?.['Authorization'] ?? '').replace('Bearer ', '')
        // The literal pins the cross-language contract: Django's dev default must match or local runs 401.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(token, 'local-dev-workflow-vision-request-jwt', {
            audience: 'posthog:workflows:vision_request',
            algorithms: ['HS256'],
        }) as jwt.JwtPayload
        expect(claims.hog_flow_id).toBe(workflowOptions.hogFlow.id)
    })

    it.each([
        [
            'parks while the scan runs',
            202,
            { request_id: 'r1', status: 'running' },
            { request_id: 'r1', await: { max_wait: '8h', label: 'Replay Vision scan' } },
        ],
        [
            'returns a settled answer in the shape a wake brings',
            202,
            { request_id: 'r1', status: 'completed', state: 'succeeded', output: { tag: 'checkout' }, warnings: null },
            { state: 'succeeded', output: { tag: 'checkout' }, warnings: null },
        ],
        [
            'skips the event at a daily limit',
            409,
            { detail: 'This workflow reached the daily limit.' },
            { state: 'skipped', output: null, warnings: ['This workflow reached the daily limit.'] },
        ],
    ])('%s', async (_name, status, body, expected) => {
        let response = await tester.invoke(inputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, { status, body })

        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual(expected)
    })

    it('fails the step on a refused scan', async () => {
        let response = await tester.invoke(inputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { detail: 'Add at least one category.' },
        })

        expect(response.error).toMatch(/Add at least one category/)
    })

    it('fails without staging a request when the event has no session', async () => {
        const response = await tester.invoke({ ...inputs, session_id: '' }, undefined, workflowOptions)
        expect(response.error).toMatch(/no session recording/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })
})
