import { TemplateTester } from '../../test/test-helpers'
import { template } from './github-request-reviewers.template'

const defaultInputs = {
    github_installation: { access_token: 'installation-token', account: { name: 'posthog' } },
    repository: 'posthog/posthog-js',
    number: '42',
    reviewers: '',
    team_reviewers: '',
}

describe('github request reviewers template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it.each([
        [
            'users only',
            { reviewers: ' reviewer-one,\treviewer-two,,' },
            '{"reviewers":["reviewer-one","reviewer-two"]}',
        ],
        ['teams only', { team_reviewers: 'web-team, ' }, '{"team_reviewers":["web-team"]}'],
        [
            'users and teams',
            { reviewers: 'reviewer-one', team_reviewers: 'web-team,platform' },
            '{"reviewers":["reviewer-one"],"team_reviewers":["web-team","platform"]}',
        ],
    ])('requests reviews from %s and leaves out an empty list', async (_case, inputs, body) => {
        const response = await tester.invoke({ ...defaultInputs, ...inputs })

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toEqual({
            type: 'fetch',
            method: 'POST',
            url: 'https://api.github.com/repos/posthog/posthog-js/pulls/42/requested_reviewers',
            headers: {
                Authorization: 'Bearer installation-token',
                Accept: 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'PostHog Github App',
                'Content-Type': 'application/json',
            },
            body,
        })
    })

    it('returns the reviewers and teams GitHub now has requested', async () => {
        const response = await tester.invoke({
            ...defaultInputs,
            reviewers: 'reviewer-one',
            team_reviewers: 'web-team',
        })
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: {
                number: 42,
                title: 'Retry flaky uploads',
                requested_reviewers: [
                    { login: 'earlier-reviewer', id: 7 },
                    { login: 'reviewer-one', id: 8 },
                ],
                requested_teams: [{ name: 'Web team', slug: 'web-team', id: 9 }],
            },
        })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toEqual({
            requested_reviewers: ['earlier-reviewer', 'reviewer-one'],
            requested_teams: ['web-team'],
        })
    })

    it.each([
        ['', ''],
        [', ,', '\t'],
    ])('rejects reviewers %j and teams %j that hold no name before any request', async (reviewers, team_reviewers) => {
        const response = await tester.invoke({ ...defaultInputs, reviewers, team_reviewers })

        expect(response.error).toEqual('Enter at least one reviewer or team')
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it.each([[null], ['<html>Unicorn!</html>'], [{ number: 42, requested_reviewers: [] }]])(
        'fails when GitHub answers with %j instead of the requested reviewers and teams',
        async (body) => {
            const response = await tester.invoke({ ...defaultInputs, reviewers: 'reviewer-one' })
            const result = await tester.invokeFetchResponse(response.invocation, { status: 201, body })

            expect(result.execResult).toBeUndefined()
            expect(result.error).toEqual(
                'Failed to request GitHub reviewers (201): GitHub returned no reviewer or team list'
            )
        }
    )

    it('fails with the status and GitHub message when GitHub rejects a reviewer', async () => {
        const response = await tester.invoke({ ...defaultInputs, reviewers: 'octo-dev' })
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 422,
            body: { message: 'Review cannot be requested from pull request author.' },
        })

        expect(result.execResult).toBeUndefined()
        expect(result.error).toEqual(
            'Failed to request GitHub reviewers (422): Review cannot be requested from pull request author.'
        )
    })
})
