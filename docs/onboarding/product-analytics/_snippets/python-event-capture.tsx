import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './person-profiles'

export const PythonEventCapture = function PythonEventCapture(): JSX.Element {
    const { Markdown, CodeBlock, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                Capture custom events by calling the `capture` method with an event name and properties:
            </Markdown>
            <CodeBlock
                blocks={[
                    {
                        language: 'python',
                        file: 'Python',
                        code: dedent`
                            import posthog
                            posthog.capture('user_123', 'user_signed_up', properties={'example_property': 'example_value'})
                        `,
                    },
                ]}
            />
            <PersonProfiles language="python" />
        </>
    )
}
