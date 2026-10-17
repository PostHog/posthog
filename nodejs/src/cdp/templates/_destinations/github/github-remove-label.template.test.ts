import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-remove-label.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
    label: 'needs review',
}

describe('github remove label template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('removes the label and reports it as removed', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'DELETE',
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/labels/needs%20review',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
            },
        })

        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: [{ id: 1, name: 'bug', color: 'd73a4a' }],
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({ removed: true })
    })

    it('keeps a label name with a slash inside the label path segment', async () => {
        const response = await tester.invoke({ ...defaultInputs, label: 'area/../workflows' })

        expect(response.invocation.queueParameters).toMatchObject({
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/labels/area%2F..%2Fworkflows',
        })
    })

    it.each([
        ['', 'Enter a label name'],
        ['   ', 'Enter a label name'],
        ['\n\t', 'Enter a label name'],
        ['.', 'A label name cannot be . or ..'],
        ['..', 'A label name cannot be . or ..'],
    ])('rejects the label %j before any request', async (label, error) => {
        const response = await tester.invoke({ ...defaultInputs, label })

        expect(response.error).toEqual(error)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('reports the label as not removed when the issue does not have it', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 404,
            body: { message: 'Label does not exist' },
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({ removed: false })
    })

    it.each([
        [404, 'Not Found', 'Failed to remove GitHub label (404): Not Found'],
        [
            403,
            'Resource not accessible by integration',
            'Failed to remove GitHub label (403): Resource not accessible by integration',
        ],
    ])('fails on a %d with message %j', async (status, message, error) => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, { status, body: { message } })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual(error)
    })
})
