import { buildPostHogCodeDeepLink } from './AgentPromptButton'

describe('AgentPromptButton', () => {
    it.each([
        ['with a repository', 'posthog/posthog', 'posthog-code://new?prompt=fix%20this&repo=posthog%2Fposthog'],
        ['without a repository', undefined, 'posthog-code://new?prompt=fix%20this'],
    ])('builds a PostHog Code deep link %s', (_, repository, expected) => {
        expect(buildPostHogCodeDeepLink('fix this', repository)).toBe(expected)
    })
})
