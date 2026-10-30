import jwt from 'jsonwebtoken'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { PosthogJwtAudience } from '../../../utils/jwt-utils'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-opt-out-of-messages.template'

describe('posthog opt out of messages template', () => {
    const tester = new TemplateTester(template)
    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' } }
    const inputs = { category_id: '0198c9f1-0000-0000-0000-0000000000aa', identifier: 'sam@example.com' }

    let fetchSpy: jest.SpyInstance
    const internalResponse = (status: number, body: unknown): requestModule.FetchResponse => ({
        status,
        headers: {},
        text: () => Promise.resolve(JSON.stringify(body)),
        json: () => Promise.resolve(body),
        dump: async () => {},
    })
    beforeEach(async () => {
        await tester.beforeEach()
        fetchSpy = jest
            .spyOn(requestModule, 'internalFetch')
            .mockResolvedValue(internalResponse(200, { result: 'opted_out', detail: 'Opted out of Product updates.' }))
    })
    afterEach(() => jest.restoreAllMocks())

    it('opts the recipient out with a token scoped to this step and workflow', async () => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        const resumed = await tester.resumeInvocation(response.invocation)

        expect(resumed.error).toBeUndefined()
        expect(resumed.logs.map((log) => log.message)).toContain('Opted out of Product updates.')
        const [url, params] = fetchSpy.mock.calls[0] as [string, requestModule.FetchOptions]
        expect(url).toBe(`${defaultConfig.INTERNAL_API_BASE_URL}/api/projects/1/workflow_message_opt_outs/`)
        expect(parseJSON(params.body!.toString())).toEqual(inputs)
        const token = (params.headers as Record<string, string>).Authorization.replace('Bearer ', '')
        expect(
            jwt.verify(token, defaultConfig.WORKFLOW_MESSAGE_OPT_OUT_JWT_SECRET, {
                audience: PosthogJwtAudience.WORKFLOW_MESSAGE_OPT_OUT,
            })
        ).toMatchObject({ team_id: 1, hog_flow_id: workflowOptions.hogFlow.id })
    })

    it.each([
        [409, 'The message category was deleted. Choose another category in the step.'],
        [
            403,
            "The saved workflow doesn't opt people out of this category. Save or publish the workflow, then try again.",
        ],
    ])('fails the step when Django refuses with %i', async (status, detail) => {
        fetchSpy.mockResolvedValue(internalResponse(status, { result: 'refused', detail }))

        const response = await tester.invoke(inputs, undefined, workflowOptions)
        const resumed = await tester.resumeInvocation(response.invocation)

        expect(resumed.error).toEqual(`Could not opt the recipient out (${status}): ${detail}`)
    })

    it.each([
        ['an empty recipient', { ...inputs, identifier: '  ' }, /no email to opt out/],
        ['no category', { ...inputs, category_id: '' }, /Choose a message category/],
    ])('fails the step without calling Django for %s', async (_name, stepInputs, expected) => {
        const response = await tester.invoke(stepInputs, undefined, workflowOptions)

        expect(response.error).toMatch(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
