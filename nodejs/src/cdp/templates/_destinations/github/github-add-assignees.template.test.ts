import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-add-assignees.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
    assignees: ' octo-dev,\n\tno-access-user,,',
}

describe('github add assignees template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('assigns the users and returns the assignees GitHub reports, without users it dropped', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'POST',
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/assignees',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
                'Content-Type': 'application/json',
            },
            body: '{"assignees":["octo-dev","no-access-user"]}',
        })

        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: {
                number: 42,
                title: 'Retry flaky uploads',
                assignees: [
                    { login: 'existing-owner', id: 3 },
                    { login: 'octo-dev', id: 5 },
                ],
            },
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({ assignees: ['existing-owner', 'octo-dev'] })
    })

    it.each([[''], [',, ,'], ['\t,\n']])(
        'rejects assignees %j that hold no username before any request',
        async (assignees) => {
            const response = await tester.invoke({ ...defaultInputs, assignees })

            expect(response.error).toEqual('Enter at least one GitHub username')
            expect(response.invocation.queueParameters).toBeUndefined()
        }
    )

    it.each([[null], ['<html>Unicorn!</html>'], [{ number: 42 }]])(
        'fails when GitHub answers with %j instead of an assignee list',
        async (body) => {
            const response = await tester.invoke(defaultInputs)
            const result = await tester.invokeFetchResponse(response.invocation, { status: 201, body })

            expect(result.execResult).toBeUndefined()
            expect(result.error).toEqual('Failed to assign GitHub users (201): GitHub returned no assignee list')
        }
    )

    it('fails with the status and GitHub message when GitHub rejects the assignees', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { message: 'Resource not accessible by integration' },
        })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual('Failed to assign GitHub users (403): Resource not accessible by integration')
    })
})
