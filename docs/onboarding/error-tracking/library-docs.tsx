import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

interface LibraryDocsOptions {
    title: string
    guidance: string
    docsLink: string
    code?: string
    language?: string
}

const createLibraryDocsSteps =
    (options: LibraryDocsOptions) =>
    (ctx: OnboardingComponentsContext): StepDefinition[] => {
        const { CodeBlock, Markdown, dedent } = ctx

        return [
            {
                title: options.title,
                badge: 'required',
                content: (
                    <>
                        <Markdown>
                            {dedent`
                                ${options.guidance}

                                [Open the SDK documentation](${options.docsLink}) for installation and configuration details.
                            `}
                        </Markdown>
                        {options.code && options.language ? (
                            <CodeBlock language={options.language} code={dedent(options.code)} />
                        ) : null}
                    </>
                ),
            },
        ]
    }

export const JavaErrorTrackingInstallation = createInstallation(
    createLibraryDocsSteps({
        title: 'Capture Java exceptions',
        guidance:
            'The Java server SDK supports manual exception capture. It does not install an uncaught-exception handler, so call `captureException` from your application or framework error handler.',
        docsLink: 'https://posthog.com/docs/libraries/java#request-context',
        language: 'java',
        code: 'posthog.captureException(error);',
    })
)

export const KMPErrorTrackingInstallation = createInstallation(
    createLibraryDocsSteps({
        title: 'Capture Kotlin Multiplatform exceptions',
        guidance:
            'The Kotlin Multiplatform SDK supports handled exceptions through `PostHog.captureException`. The shared KMP API does not currently enable automatic exception capture.',
        docsLink: 'https://posthog.com/docs/libraries/kmp#error-tracking',
        language: 'kotlin',
        code: `try {
    riskyOperation()
} catch (error: Exception) {
    PostHog.captureException(error)
}`,
    })
)

export const ConvexErrorTrackingInstallation = createInstallation(
    createLibraryDocsSteps({
        title: 'Capture Convex exceptions',
        guidance:
            "Configure Convex's first-party PostHog Error Tracking destination to capture uncaught exceptions automatically. Convex exception reporting currently requires a Convex Pro plan. Use `captureException` for handled errors that need custom properties.",
        docsLink: 'https://posthog.com/docs/libraries/convex#6-capture-exceptions-with-custom-properties',
        language: 'typescript',
        code: `await posthog.captureException(ctx, {
    error,
    distinctId: userId,
    additionalProperties: { flow: "checkout" },
})`,
    })
)
