import { memo } from 'react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ReloadFlagsSnippet = memo(function ReloadFlagsSnippet({ language = 'javascript' }: { language?: string }): JSX.Element {
    const { CodeBlock, dedent } = useMDXComponents()

    const snippets: Record<string, string> = {
        javascript: dedent`
            posthog.reloadFeatureFlags()
        `,
        'node.js': dedent`
            // Feature flags are evaluated on each call, no reload needed
        `,
        python: dedent`
            # Feature flags are evaluated on each call, no reload needed
        `,
        php: dedent`
            // Feature flags are evaluated on each call, no reload needed
        `,
        ruby: dedent`
            # Feature flags are evaluated on each call, no reload needed
        `,
        go: dedent`
            // Feature flags are evaluated on each call, no reload needed
        `,
        'react-native': dedent`
            posthog.reloadFeatureFlagsAsync().then((refreshedFlags) => console.log(refreshedFlags))
        `,
        android: dedent`
            PostHog.reloadFeatureFlags()
        `,
        ios: dedent`
            PostHogSDK.shared.reloadFeatureFlags()
        `,
        flutter: dedent`
            await Posthog().reloadFeatureFlags()
        `,
    }

    const langMap: Record<string, string> = {
        javascript: 'javascript',
        'node.js': 'javascript',
        python: 'python',
        php: 'php',
        ruby: 'ruby',
        go: 'go',
        'react-native': 'javascript',
        android: 'kotlin',
        ios: 'swift',
        flutter: 'dart',
    }

    return <CodeBlock language={langMap[language] || 'javascript'} code={snippets[language] || snippets.javascript} />
})
