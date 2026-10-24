import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-create-comment.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
    body: 'This PR left the merge queue. <!-- merge-queue-warning -->',
}

describe('github create comment template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('posts the comment and returns its id and url', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'POST',
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/comments',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
                'Content-Type': 'application/json',
            },
            body: '{"body":"This PR left the merge queue. <!-- merge-queue-warning -->"}',
        })

        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: {
                id: 7,
                body: defaultInputs.body,
                html_url: 'https://github.com/posthog/posthog-js/pull/42#issuecomment-7',
                user: { login: 'posthog[bot]' },
            },
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({
            comment_id: 7,
            html_url: 'https://github.com/posthog/posthog-js/pull/42#issuecomment-7',
        })
    })

    it('rejects an empty comment before any request', async () => {
        const response = await tester.invoke({ ...defaultInputs, body: '' })

        expect(response.error).toEqual('Comment is required')
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('fails with the status and GitHub message when GitHub rejects the comment', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { message: 'Resource not accessible by integration' },
        })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual('Failed to add GitHub comment (403): Resource not accessible by integration')
    })
})
