import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const BooleanFlagSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            const result = posthog.getFeatureFlagResult('flag-key')
            if (result?.enabled) {
                // Do something differently for this user
                // Optional: use the flag payload
                const matchedFlagPayload = result.payload
            }
        `,
        react: dedent`
            import { useFeatureFlagResult } from '@posthog/react'

            function App() {
                const result = useFeatureFlagResult('flag-key')
                return (
                    <div className="App">
                        {result?.enabled ? (
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
            const result = await client.getFeatureFlagResult('flag-key', 'distinct_id_of_your_user')
            if (result?.enabled) {
                // Do something differently for this user
                // Optional: use the flag payload
                const matchedFlagPayload = result.payload
            }
        `,
        python: dedent`
            result = posthog.get_feature_flag_result('flag-key', 'distinct_id_of_your_user')
            if result and result.enabled:
                # Do something differently for this user
                # Optional: use the flag payload
                matched_flag_payload = result.payload
        `,
        php: dedent`
            $result = PostHog::getFeatureFlagResult('flag-key', 'distinct_id_of_your_user');
            if ($result?->isEnabled()) {
                // Do something differently for this user
                // Optional: use the flag payload
                $matchedFlagPayload = $result->getPayload();
            }
        `,
        ruby: dedent`
            result = posthog.get_feature_flag_result('flag-key', 'distinct_id_of_your_user')
            if result&.enabled?
                # Do something differently for this user
                # Optional: use the flag payload
                matched_flag_payload = result.payload
            end
        `,
        go: dedent`
            result, err := client.GetFeatureFlagResult(posthog.FeatureFlagPayload{
                Key:        "flag-key",
                DistinctId: "distinct_id_of_your_user",
            })
            if err != nil {
                // Handle error
                return
            }

            if result.Enabled {
                // Do something differently for this user
                // Optional: use the flag payload
                if result.RawPayload != nil {
                    fmt.Println(*result.RawPayload)
                }
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


