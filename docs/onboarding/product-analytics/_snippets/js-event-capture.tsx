import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const JSEventCapture = function JSEventCapture(): JSX.Element {
    const { Markdown, CodeBlock, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                Click around and view a couple pages to generate some events. PostHog automatically captures pageviews,
                clicks, and other interactions for you.
            </Markdown>
            <Markdown>If you'd like, you can also manually capture custom events:</Markdown>
            <CodeBlock
                blocks={[
                    {
                        language: 'javascript',
                        file: 'JavaScript',
                        code: dedent`
                            posthog.capture('my_custom_event', { property: 'value' })
                        `,
                    },
                ]}
            />
        </>
    )
}
