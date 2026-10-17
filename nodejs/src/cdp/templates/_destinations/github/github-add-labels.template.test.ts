import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-add-labels.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
    labels: 'bug,\n\tneeds review,,',
}

describe('github add labels template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('adds the labels and returns every label now on the issue', async () => {
        const response = await tester.invoke(defaultInputs)

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'POST',
            url: 'https://api.github.com/repos/posthog/posthog-js/issues/42/labels',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
                'Content-Type': 'application/json',
            },
            body: '{"labels":["bug","needs review"]}',
        })

        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: [
                { id: 1, name: 'triage', color: 'ededed' },
                { id: 2, name: 'bug', color: 'd73a4a' },
                { id: 3, name: 'needs review', color: 'fbca04' },
            ],
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({ labels: ['triage', 'bug', 'needs review'] })
    })

    it.each([[''], [',, ,'], ['   '], ['\t,\n']])(
        'rejects labels %j that hold no label name before any request',
        async (labels) => {
            const response = await tester.invoke({ ...defaultInputs, labels })

            expect(response.error).toEqual('Enter at least one label name')
            expect(response.invocation.queueParameters).toBeUndefined()
        }
    )

    it.each([
        [null, 'Failed to add GitHub labels (200): GitHub returned no label list'],
        ['<html>Unicorn!</html>', 'Failed to add GitHub labels (200): GitHub returned no label list'],
        [[{ id: 1 }], 'Failed to add GitHub labels (200): GitHub returned a label without a name'],
    ])('fails when GitHub answers with %j instead of a label list', async (body, error) => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, { status: 200, body })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual(error)
    })

    it('fails with the status and GitHub message when GitHub rejects the labels', async () => {
        const response = await tester.invoke(defaultInputs)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { message: 'Resource not accessible by integration' },
        })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual('Failed to add GitHub labels (403): Resource not accessible by integration')
    })
})
