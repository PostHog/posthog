import { buildPostHogCodeDeepLink, buildPostHogTaskUrl } from './AgentPromptButton'

describe('AgentPromptButton', () => {
    it('builds a new web task url that carries the prompt in the ask param', () => {
        expect(buildPostHogTaskUrl('fix this & that')).toBe('/tasks/new?ask=fix%20this%20%26%20that')
    })

    it.each([
        ['with a repository', 'posthog/posthog', 'posthog-code://new?prompt=fix%20this&repo=posthog%2Fposthog'],
        ['without a repository', undefined, 'posthog-code://new?prompt=fix%20this'],
    ])('builds a PostHog Code deep link %s', (_, repository, expected) => {
        expect(buildPostHogCodeDeepLink('fix this', repository)).toBe(expected)
    })
})
