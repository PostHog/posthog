import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getIOSSteps } from '../product-analytics/ios'
import { StepDefinition } from '../steps'

function getSurveysIOSSteps(ctx: OnboardingComponentsContext): StepDefinition[] {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const SurveysFinalSteps = snippets?.SurveysFinalSteps

    const installationSteps = getIOSSteps(ctx)

    const surveysSteps: StepDefinition[] = [
        {
            title: 'Enable surveys in your configuration',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        To enable surveys in your iOS app, enable surveys in your PostHog configuration:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'AppDelegate.swift',
                                code: dedent`
                                    let POSTHOG_PROJECT_TOKEN = "<ph_project_token>"
                                    // usually 'https://us.i.posthog.com' or 'https://eu.i.posthog.com'
                                    let POSTHOG_HOST = "<ph_client_api_host>"
                                    let config = PostHogConfig(apiKey: POSTHOG_PROJECT_TOKEN, host: POSTHOG_HOST) 

                                    // Surveys require iOS 15.0 or later
                                    if #available(iOS 15.0, *) {
                                        config.surveys = true
                                    }

                                    PostHogSDK.shared.setup(config)
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]

    return [
        ...installationSteps,
        ...surveysSteps,
        {
            title: 'Next steps',
            badge: 'recommended',
            content: <>{SurveysFinalSteps && <SurveysFinalSteps />}</>,
        },
    ]
}

export const SurveysIOSInstallation = createInstallation(getSurveysIOSSteps)
