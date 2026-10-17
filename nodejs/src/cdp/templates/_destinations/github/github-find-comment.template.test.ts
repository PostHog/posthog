import { MAX_ASYNC_STEPS } from '~/cdp/services/hog-executor.service'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-find-comment.template'

const installation = { access_token: 'installation-token', account: { name: 'posthog' } }

const defaultInputs = {
    github_installation: installation,
    repository: 'posthog-js',
    number: '42',
    text: '<!-- merge-queue-warning -->',
}

describe('github find comment template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('requests the first page of issue comments with the GitHub App headers', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'GET',
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/comments?per_page=100&page=1',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
            },
        })
    })

    it.each([
        ['a bare repository name under the installation account', 'posthog-js', 'posthog/posthog-js'],
        ['an owner/repo pair as is', 'other-org/some.repo_name', 'other-org/some.repo_name'],
    ])('resolves %s', async (_, repository, expectedPath) => {
        const response = await tester.invoke({ ...defaultInputs, repository })

        expect(response.invocation.queueParameters).toMatchObject({
            url: `https://api.github.com/repos/${expectedPath}/issues/42/comments?per_page=100&page=1`,
        })
    })

    it.each([
        ['a path traversal', { repository: '../x' }, 'Repository must be a repository name or owner/repo'],
        ['a dot segment', { repository: 'posthog/..' }, 'Repository must be a repository name or owner/repo'],
        ['too many segments', { repository: 'a/b/c' }, 'Repository must be a repository name or owner/repo'],
        ['an empty repository', { repository: '' }, 'Repository must be a repository name or owner/repo'],
        ['a zero number', { number: '0' }, 'Issue or PR number must be a positive whole number'],
        ['a non-numeric number', { number: 'abc' }, 'Issue or PR number must be a positive whole number'],
        ['a number with a path suffix', { number: '42/../../x' }, 'Issue or PR number must be a positive whole number'],
        ['empty search text', { text: '' }, 'Comment text is required'],
    ])('rejects %s before any request', async (_, inputs, message) => {
        const response = await tester.invoke({ ...defaultInputs, ...inputs })

        expect(response.error).toEqual(message)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('returns the first comment that contains the text', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: [
                comment(1, 'Looks good to me'),
                comment(2, 'Heads up <!-- merge-queue-warning -->'),
                comment(3, 'Again <!-- merge-queue-warning -->'),
            ],
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({ found: true, comment_id: 2, html_url: commentUrl(2) })
    })

    it('returns not found after a page with fewer than 100 comments', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: [comment(1, 'Looks good to me'), comment(2, '<!-- MERGE-QUEUE-WARNING -->')],
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toStrictEqual({ found: false, comment_id: null, html_url: null })
    })

    it('searches the next page when a full page has no match', async () => {
        const response = await tester.invoke(defaultInputs)
        const secondPage = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: fullPageWithoutMatch(),
        })

        expect(secondPage.finished).toBe(false)
        expect(secondPage.invocation.queueParameters).toMatchObject({
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/comments?per_page=100&page=2',
        })

        const result = await tester.invokeFetchResponse(secondPage.invocation, {
            status: 200,
            body: [comment(101, '<!-- merge-queue-warning -->')],
        })

        expect(result.execResult).toEqual({ found: true, comment_id: 101, html_url: commentUrl(101) })
    })

    it('fails when every page the step may fetch is full and has no match', async () => {
        let result = await tester.invoke(defaultInputs)
        for (let page = 1; page <= MAX_ASYNC_STEPS; page++) {
            expect(result.invocation.queueParameters).toMatchObject({ url: expect.stringContaining(`&page=${page}`) })
            result = await tester.invokeFetchResponse(result.invocation, { status: 200, body: fullPageWithoutMatch() })
        }

        expect(result.finished).toBe(true)
        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual(
            'Searched the first 500 comments and found no match. The issue or PR has more comments than this step can search.'
        )
    })

    it.each([
        ['GitHub rejects the request', 404, { message: 'Not Found' }, 'Failed to find GitHub comment (404): Not Found'],
        ['GitHub answers with a plain body', 502, 'Bad gateway', 'Failed to find GitHub comment (502): Bad gateway'],
        [
            'a successful response has no comment list',
            200,
            { message: 'Moved' },
            'Failed to find GitHub comment (200): GitHub returned no comment list',
        ],
        [
            'a comment on the page has no readable body',
            200,
            [comment(1, 'Looks good to me'), { id: 2, body: null, html_url: commentUrl(2) }],
            'Failed to find GitHub comment (200): GitHub returned a comment without a body',
        ],
    ])('fails instead of returning not found when %s', async (_, status, body, message) => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, { status, body })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual(message)
    })
})

function commentUrl(id: number): string {
    return `https://github.com/posthog/posthog-js/pull/42#issuecomment-${id}`
}

function comment(id: number, body: string): { id: number; body: string; html_url: string } {
    return { id, body, html_url: commentUrl(id) }
}

function fullPageWithoutMatch(): ReturnType<typeof comment>[] {
    return Array.from({ length: 100 }, (_, index) => comment(index + 1, 'Unrelated comment'))
}
