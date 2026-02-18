import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const FlagPayloadSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            const result = posthog.getFeatureFlagResult('flag-key')
            if (result?.payload) {
                console.log(result.payload)
            }
        `,
        react: dedent`
            import { useFeatureFlagResult } from '@posthog/react'

            function App() {
                const result = useFeatureFlagResult('show-welcome-message')
                return (
                    <>
                        {result?.enabled ? (
                            <div className="welcome-message">
                                <h2>{result?.payload?.welcomeTitle}</h2>
                                <p>{result?.payload?.welcomeMessage}</p>
                            </div>
                        ) : (
                            <div>
                                <h2>No custom welcome message</h2>
                                <p>Because the feature flag evaluated to false.</p>
                            </div>
                        )}
                    </>
                )
            }
        `,
        'node.js': dedent`
            const result = await client.getFeatureFlagResult('flag-key', 'distinct_id_of_your_user')
            if (result?.payload) {
                console.log(result.payload)
            }
        `,
        python: dedent`
            result = posthog.get_feature_flag_result('flag-key', 'distinct_id_of_your_user')
            if result and result.payload:
                print(result.payload)
        `,
        php: dedent`
            $result = PostHog::getFeatureFlagResult('flag-key', 'distinct_id_of_your_user');
            if ($result?->getPayload()) {
                echo $result->getPayload();
            }
        `,
        ruby: dedent`
            result = posthog.get_feature_flag_result('flag-key', 'distinct_id_of_your_user')
            if result&.payload
                puts result.payload
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
                // Unmarshal the payload into a typed struct
                var config MyConfig
                if err := result.GetPayloadAs(&config); err == nil {
                    fmt.Println(config)
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
