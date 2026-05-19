import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const MobileFinalSteps = (): JSX.Element => {
    const { Markdown } = useMDXComponents()

    return (
        <>
            <Markdown>
                Despite the name, the web analytics dashboard can be used to track screen views in mobile apps, too.
                Open your app and view some screens to generate some events.
            </Markdown>
        </>
    )
}
