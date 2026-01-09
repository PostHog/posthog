import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const BooleanFlagSnippet = memo(function BooleanFlagSnippet({ language = 'javascript' }: { language?: string }): JSX.Element {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            if (posthog.isFeatureEnabled('flag-key')) {
                // Do something differently for this user
                // Optional: fetch the payload
                const matchedFlagPayload = posthog.getFeatureFlagPayload('flag-key')
            }
        `,
        react: dedent`
            import { useFeatureFlagEnabled } from '@posthog/react'

            function App() {
                const showWelcomeMessage = useFeatureFlagEnabled('flag-key')
                const payload = useFeatureFlagPayload('flag-key')
                return (
                    <div className="App">
                        {showWelcomeMessage ? (
                            <div>
                                <h1>Welcome!</h1>
                                <p>Thanks for trying out our feature flags.</p>
                            </div>
                        ) : (
                            <div>
                                <h2>No welcome message</h2>
                                <p>Because the feature flag evaluated to false.</p>
                            </div>
                        )}
                    </div>
                )
            }
        `,
        'node.js': dedent`
            const isFeatureFlagEnabled = await client.isFeatureEnabled('flag-key', 'distinct_id_of_your_user')
            if (isFeatureFlagEnabled) {
                // Your code if the flag is enabled
                // Optional: fetch the payload
                const matchedFlagPayload = await client.getFeatureFlagPayload('flag-key', 'distinct_id_of_your_user', isFeatureFlagEnabled)
            }
        `,
        python: dedent`
            is_my_flag_enabled = posthog.feature_enabled('flag-key', 'distinct_id_of_your_user')
            if is_my_flag_enabled:
                # Do something differently for this user
                # Optional: fetch the payload
                matched_flag_payload = posthog.get_feature_flag_payload('flag-key', 'distinct_id_of_your_user')
        `,
        php: dedent`
            $isMyFlagEnabledForUser = PostHog::isFeatureEnabled('flag-key', 'distinct_id_of_your_user')
            if ($isMyFlagEnabledForUser) {
                // Do something differently for this user
            }
        `,
        ruby: dedent`
            is_my_flag_enabled = posthog.is_feature_enabled('flag-key', 'distinct_id_of_your_user')
            if is_my_flag_enabled
                # Do something differently for this user
                # Optional: fetch the payload
                matched_flag_payload = posthog.get_feature_flag_payload('flag-key', 'distinct_id_of_your_user')
            end
        `,
        go: dedent`
            isMyFlagEnabled, err := client.IsFeatureEnabled(posthog.FeatureFlagPayload{
                Key:        "flag-key",
                DistinctId: "distinct_id_of_your_user",
            })
            if err != nil {
                // Handle error (e.g. capture error and fallback to default behaviour)
            }
            if isMyFlagEnabled == true {
                // Do something differently for this user
            }
        `,
    }

    const langMap: Record<string, string> = {
        javascript: 'javascript',
        react: 'jsx',
        'node.js': 'javascript',
        python: 'python',
        php: 'php',
        ruby: 'ruby',
        go: 'go',
    }

    return <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
})


