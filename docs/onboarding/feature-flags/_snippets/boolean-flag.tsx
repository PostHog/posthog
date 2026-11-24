import { memo } from 'react'

import { useMDXComponents } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

export const BooleanFlagSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            if (posthog.isFeatureEnabled('flag-key')) {
                // Do something differently for this user
                // Optional: fetch the payload
                const matchedFlagPayload = posthog.getFeatureFlagResult('flag-key')?.payload
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
            const flags = await client.evaluateFlags('distinct_id_of_your_user', { flagKeys: ['flag-key'] })
            if (flags.isEnabled('flag-key')) {
                // Your code if the flag is enabled
                // Optional: fetch the payload
                const matchedFlagPayload = flags.getFlagPayload('flag-key')
            }
        `,
        python: dedent`
            flags = posthog.evaluate_flags('distinct_id_of_your_user', flag_keys=['flag-key'])
            if flags.is_enabled('flag-key'):
                # Do something differently for this user
                # Optional: fetch the payload
                matched_flag_payload = flags.get_flag_payload('flag-key')
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
            flags, err := client.EvaluateFlags(posthog.EvaluateFlagsPayload{
                DistinctId: "distinct_id_of_your_user",
                FlagKeys:   []string{"flag-key"},
            })
            if err != nil {
                // Handle error (e.g. capture error and fallback to default behaviour)
            }
            if flags != nil && flags.IsEnabled("flag-key") {
                // Do something differently for this user
                // Optional: fetch the payload
                matchedFlagPayload := flags.GetFlagPayload("flag-key")
                _ = matchedFlagPayload
            }
        `,
        dotnet: dedent`
            var flags = await posthog.EvaluateFlagsAsync("distinct_id_of_your_user");

            if (flags.IsEnabled("flag-key"))
            {
                // Do something differently for this user
                // Optional: fetch the payload
                var matchedFlagPayload = flags.GetFlagPayload("flag-key");
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
        dotnet: 'csharp',
    }

    return <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
})
