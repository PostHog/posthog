import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-update-issue.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
    title: '',
    body: '',
    state: '',
}

describe('github update issue template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it.each([
        ['the state only', { state: 'closed' }, '{"state":"closed"}'],
        ['the title only', { title: '[Stale] Retry flaky uploads' }, '{"title":"[Stale] Retry flaky uploads"}'],
        [
            'the title and body',
            { title: 'Retry flaky uploads', body: 'Fixes upload retries.' },
            '{"title":"Retry flaky uploads","body":"Fixes upload retries."}',
        ],
    ])('sends %s to the issues endpoint', async (_, inputs, expectedBody) => {
        const response = await tester.invoke({ ...defaultInputs, ...inputs })

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'PATCH',
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
                'Content-Type': 'application/json',
            },
            body: expectedBody,
        })
    })

    it('rejects an update with nothing to change before any request', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toEqual('Set a title, body, or state to update')
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('returns the number, title, state, and url of the updated issue or PR', async () => {
        const response = await tester.invoke({ ...defaultInputs, state: 'closed' })
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: {
                id: 1001,
                number: 42,
                title: 'Retry flaky uploads',
                body: 'Long description that must not reach workflow variables',
                state: 'closed',
                state_reason: 'completed',
                html_url: 'https://github.com/posthog/posthog-js/pull/42',
                user: { login: 'octo-dev' },
                pull_request: { url: 'https://api.github.com/repos/posthog/posthog-js/pulls/42' },
            },
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toStrictEqual({
            number: 42,
            title: 'Retry flaky uploads',
            state: 'closed',
            html_url: 'https://github.com/posthog/posthog-js/pull/42',
        })
    })

    it('fails with the status and GitHub message when GitHub rejects the update', async () => {
        const response = await tester.invoke({ ...defaultInputs, state: 'open' })
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 422,
            body: { message: 'state cannot be changed. The pull request cannot be reopened.' },
        })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual(
            'Failed to update GitHub issue or PR (422): state cannot be changed. The pull request cannot be reopened.'
        )
    })
})
