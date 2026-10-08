import jwt from 'jsonwebtoken'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-analyze-sessions.template'

describe('posthog analyze sessions template', () => {
    const tester = new TemplateTester(template)

    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'action_1' }
    const inputs = { session_id: 'session-1', prompt: 'Did the user rage click?' }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('stages an authenticated scan request keyed to this step', async () => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        expect(response.error).toBeUndefined()

        const params = response.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
        expect(params.url).toMatch(/\/api\/projects\/1\/workflow_vision_requests\/$/)
        expect(parseJSON(params.body!)).toEqual({
            session_ids: ['session-1'],
            prompt: 'Did the user rage click?',
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
        ['running', { request_id: 'r1', status: 'running', await: { max_wait: '120m', label: 'Replay vision scan' } }],
        ['completed', { request_id: 'r1', status: 'completed' }],
    ])('parks the step only while the scan is %s', async (scanStatus, expected) => {
        let response = await tester.invoke(inputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, {
            status: 202,
            body: { request_id: 'r1', status: scanStatus },
        })

        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual(expected)
    })

    it('fails without staging a request when the event has no session', async () => {
        const response = await tester.invoke({ ...inputs, session_id: '' }, undefined, workflowOptions)
        expect(response.error).toMatch(/no session recording/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })
})
