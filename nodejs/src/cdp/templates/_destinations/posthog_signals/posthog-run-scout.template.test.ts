import jwt from 'jsonwebtoken'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-run-scout.template'

describe('posthog run scout template', () => {
    const tester = new TemplateTester(template)

    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'action_1' }
    const inputs = { skill_name: 'signals-scout-error-tracking' }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('stages an authenticated run request with a step-scoped idempotency key', async () => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const params = response.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
        expect(params.type).toBe('fetch')
        expect(params.method).toBe('POST')
        expect(params.url).toMatch(/\/api\/projects\/1\/workflow_scout_runs\/$/)
        // Dispatch opens a Temporal connection server-side, so the default 3s budget is too tight.
        expect(params.timeoutMs).toBe(15_000)
        // A 429 is the cooldown or budget, which the retry backoff cannot outwait.
        expect(params.nonRetriableStatusCodes).toEqual([429])

        // The triggering event is deliberately absent: v1 is a pure kick, so the run's prompt is
        // identical to a scheduled run's.
        expect(parseJSON(params.body!)).toEqual({
            skill_name: 'signals-scout-error-tracking',
            idempotency_key: `${response.invocation.id}:action_1`,
        })

        const token = (params.headers?.['Authorization'] ?? '').replace('Bearer ', '')
        // The literal pins the cross-language contract: Django's SIGNALS_SCOUT_RUN_JWT_SECRET dev
        // default (posthog/settings/data_stores.py) must match the nodejs one or local runs 401.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(token, 'local-dev-signals-scout-run-jwt', {
            audience: 'posthog:signals:scout_run',
            algorithms: ['HS256'],
        }) as jwt.JwtPayload
        expect(claims.team_id).toBe(1)
        expect(claims.hog_flow_id).toBe(workflowOptions.hogFlow.id)
    })

    it('fails without staging a request when no scout is chosen', async () => {
        const response = await tester.invoke({ skill_name: '' }, undefined, workflowOptions)
        expect(response.error).toMatch(/A scout is required/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('fails when invoked outside a workflow', async () => {
        const response = await tester.invoke(inputs)
        expect(response.error).toMatch(/inside a workflow/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('returns the dispatched run on a 202 response', async () => {
        let response = await tester.invoke(inputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, {
            status: 202,
            body: { skill_name: 'signals-scout-error-tracking', workflow_id: 'wf-1', started: true },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({
            skill_name: 'signals-scout-error-tracking',
            workflow_id: 'wf-1',
            started: true,
        })
    })

    it.each([
        [409, 'A run for this scout is already in progress.'],
        [429, 'This scout was already run from a workflow in the last 30 minutes.'],
    ])('skips instead of failing on a %i response', async (status, detail) => {
        let response = await tester.invoke(inputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, { status, body: { detail } })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({ skipped: true, reason: detail })
        expect(response.logs.map((log) => log.message)).toContain(`Scout not run: ${detail}`)
    })

    it.each([
        [403, 'Signals scouts are not enabled for this project.'],
        [404, "No scout named 'signals-scout-typo' exists in this project."],
    ])('surfaces the API error on a %i response', async (status, detail) => {
        let response = await tester.invoke(inputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, { status, body: { detail } })

        expect(response.error).toEqual(`Failed to run scout (${status}): ${detail}`)
    })

    it('declares 409 and 429 as non-failure statuses so the engine does not fail the step first', () => {
        const entry = template.inputs_schema.find((input) => input.type === 'non_failure_status_codes')
        expect(entry?.default).toEqual([409, 429])
    })
})
