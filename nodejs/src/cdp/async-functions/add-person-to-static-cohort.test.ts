import jwt from 'jsonwebtoken'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { template } from '../templates/_destinations/posthog_workflows/posthog-add-person-to-static-cohort.template'
import { MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import './add-person-to-static-cohort'

describe('postHogAddPersonToStaticCohort', () => {
    const payload = { cohort_id: 123, person_uuid: '0199aabb-ccdd-0000-1122-334455667788' }
    let fetchSpy: jest.SpyInstance

    beforeEach(() => {
        fetchSpy = jest.spyOn(requestModule, 'internalFetch').mockResolvedValue({
            status: 200,
            text: () => Promise.resolve(JSON.stringify({ result: 'added', detail: 'Person was added.' })),
        } as requestModule.FetchResponse)
    })
    afterEach(() => jest.restoreAllMocks())

    it('writes clear result details to the workflow log', () => {
        expect(template.code).toContain('print(response.body.detail)')
        expect(template.code).toContain('apiErrorMessage(response)')
    })

    it('posts a person and cohort with a workflow-scoped token', async () => {
        const invocation = { ...createExampleInvocation(), hogFlow: { id: 'flow-1' } }
        await getAsyncFunctionHandler('postHogAddPersonToStaticCohort')!.execute(
            [payload],
            {
                invocation,
                internalApiBaseUrl: defaultConfig.INTERNAL_API_BASE_URL,
                consumeInlineAsyncBudget: () => {},
            } as unknown as AsyncFunctionContext,
            createInvocationResult<typeof invocation>(invocation)
        )

        const [url, options] = fetchSpy.mock.calls[0]
        expect(url).toMatch(/\/api\/projects\/1\/workflow_cohort_memberships\/$/)
        expect(parseJSON(options.body)).toEqual(payload)
        const token = options.headers.Authorization.replace('Bearer ', '')
        expect(
            jwt.verify(token, defaultConfig.WORKFLOW_ADD_STATIC_COHORT_MEMBER_JWT_SECRET, {
                audience: 'posthog:workflows:add_static_cohort_member',
                algorithms: ['HS256'],
            })
        ).toMatchObject({ team_id: 1, hog_flow_id: 'flow-1' })
    })

    it.each([
        ['a missing cohort', { ...payload, cohort_id: null }, /Select a static cohort/],
        ['a missing person', { ...payload, person_uuid: null }, /This workflow run has no person/],
    ])('rejects %s in mocked and live calls', async (_name, args, expected) => {
        const invocation = { ...createExampleInvocation(), hogFlow: { id: 'flow-1' } }
        expect(() =>
            getAsyncFunctionHandler('postHogAddPersonToStaticCohort')!.mock([args], [] as MinimalLogEntry[])
        ).toThrow(expected)
        await expect(
            getAsyncFunctionHandler('postHogAddPersonToStaticCohort')!.execute(
                [args],
                {
                    invocation,
                    internalApiBaseUrl: defaultConfig.INTERNAL_API_BASE_URL,
                    consumeInlineAsyncBudget: () => {},
                } as unknown as AsyncFunctionContext,
                createInvocationResult<typeof invocation>(invocation)
            )
        ).rejects.toThrow(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
