import { memo } from 'react'

import { useMDXComponents } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

export const FlagPayloadSnippet = memo(({ language = 'javascript' }: { language?: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            const matchedFlagPayload = posthog.getFeatureFlagResult('flag-key')?.payload
        `,
        react: dedent`
            import { useFeatureFlagPayload, useFeatureFlagEnabled } from '@posthog/react'

            function App() {
                const variant = useFeatureFlagEnabled('show-welcome-message')
                const payload = useFeatureFlagPayload('show-welcome-message')
                return (
                    <>
                        {variant ? (
                            <div className="welcome-message">
                                <h2>{payload?.welcomeTitle}</h2>
                                <p>{payload?.welcomeMessage}</p>
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
            const flags = await client.evaluateFlags('distinct_id_of_your_user', { flagKeys: ['flag-key'] })
            const matchedFlagPayload = flags.getFlagPayload('flag-key')
        `,
        python: dedent`
            flags = posthog.evaluate_flags('distinct_id_of_your_user', flag_keys=['flag-key'])
            matched_flag_payload = flags.get_flag_payload('flag-key')
        `,
        php: dedent`
            // Payloads are returned as part of the flag evaluation
        `,
        ruby: dedent`
            matched_flag_payload = posthog.get_feature_flag_payload('flag-key', 'distinct_id_of_your_user')
        `,
        go: dedent`
            // Payloads are returned as part of the flag evaluation
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
