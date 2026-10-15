import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-extract.template'

describe('posthog extract template', () => {
    const tester = new TemplateTester(template)
    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'action_1' }
    const inputs = {
        context: { message: 'Opened https://github.com/example/repo/pull/7' },
        fields: { pr_url: 'The URL of the pull request' },
    }
    const internalResponse = (status: number, body: unknown): requestModule.FetchResponse => ({
        status,
        headers: {},
        text: () => Promise.resolve(JSON.stringify(body)),
        json: () => Promise.resolve(body),
        dump: async () => {},
    })

    let fetchSpy: jest.SpyInstance
    beforeEach(async () => {
        await tester.beforeEach()
        fetchSpy = jest.spyOn(requestModule, 'internalFetch')
    })
    afterEach(() => jest.restoreAllMocks())

    it('returns the values, so each output variable reads its field by name', async () => {
        fetchSpy.mockResolvedValue(
            internalResponse(200, { values: { pr_url: 'https://github.com/example/repo/pull/7' } })
        )

        const invocation = await tester.invoke(inputs, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)

        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual({ pr_url: 'https://github.com/example/repo/pull/7' })
    })

    it('reads the final message of the default AI task step by default', async () => {
        fetchSpy.mockResolvedValue(internalResponse(200, { values: { pr_url: null, summary: null } }))
        const completedTask = { run_id: 'run-1', output: {}, final_message: 'Opened a pull request' }

        await tester.invoke({}, { variables: { task: completedTask } }, workflowOptions)

        expect(parseJSON(fetchSpy.mock.calls[0][1].body).context).toEqual({ message: 'Opened a pull request' })
    })

    it('fails the step with the reason when the model gives an unusable answer', async () => {
        fetchSpy.mockResolvedValue(
            internalResponse(422, { detail: "The model returned a value that does not match its field's type." })
        )

        const invocation = await tester.invoke(inputs, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)

        expect(response.error).toEqual(
            "Could not extract (422): The model returned a value that does not match its field's type."
        )
        expect(response.execResult).toBeUndefined()
    })
})
