import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-get-pull-request.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
}

const pullRequestResponse = {
    id: 1001,
    number: 42,
    title: 'Retry flaky uploads',
    body: 'Long description that must not reach workflow variables',
    state: 'open',
    draft: false,
    merged: false,
    mergeable_state: 'clean',
    html_url: 'https://github.com/posthog/posthog-js/pull/42',
    user: { login: 'octo-dev', id: 5 },
    head: { ref: 'fix/retry-uploads', sha: 'a1b2c3d4', repo: { full_name: 'posthog/posthog-js' } },
    base: { ref: 'main', sha: 'e5f6a7b8', repo: { full_name: 'posthog/posthog-js' } },
    labels: [
        { id: 1, name: 'bug', color: 'd73a4a' },
        { id: 2, name: 'needs review', color: 'fbca04' },
    ],
    requested_reviewers: [{ login: 'reviewer-one' }],
}

describe('github get pull request template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('fetches the pull request and returns its state, branches, and label names', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'GET',
            url: 'https://api.github.com/repos/posthog/posthog-js/pulls/42',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
            },
        })

        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: pullRequestResponse,
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toStrictEqual({
            number: 42,
            title: 'Retry flaky uploads',
            state: 'open',
            draft: false,
            merged: false,
            author: 'octo-dev',
            head_ref: 'fix/retry-uploads',
            head_sha: 'a1b2c3d4',
            base_ref: 'main',
            html_url: 'https://github.com/posthog/posthog-js/pull/42',
            labels: ['bug', 'needs review'],
        })
    })

    it('fails with the status and GitHub message when the pull request cannot be read', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 404,
            body: { message: 'Not Found' },
        })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual('Failed to get GitHub pull request (404): Not Found')
    })
})
