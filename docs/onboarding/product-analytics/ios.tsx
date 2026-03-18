import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getIOSSteps = (
    ctx: OnboardingComponentsContext,
    options?: {
        includeExperimentalSpi?: boolean
        experimentalDescription?: string
        minVersionPod?: string
        minVersionSPM?: string
    }
): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const podVersion = options?.minVersionPod || '3.0'
    const spmVersion = options?.minVersionSPM || '3.0.0'

    return [
        {
            title: 'Install dependency',
            badge: 'required',
            content: (
                <>
                    {options?.experimentalDescription && (
                        <CalloutBox type="fyi" title="Experimental API">
                            <Markdown>{options.experimentalDescription}</Markdown>
                        </CalloutBox>
                    )}
                    <Markdown>Install via Swift Package Manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Package.swift',
                                code: dedent`
                                    dependencies: [
                                      .package(url: "https://github.com/PostHog/posthog-ios.git", from: "${spmVersion}")
                                    ]
                                `,
                            },
                        ]}
                    />
                    <Markdown>Or add PostHog to your Podfile:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'ruby',
                                file: 'Podfile',
                                code: dedent`
                                    pod "PostHog", "~> ${podVersion}"
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>Initialize PostHog in your AppDelegate:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'AppDelegate.swift',
                                code: dedent`
                                    import Foundation
                                    ${options?.includeExperimentalSpi ? '@_spi(Experimental) ' : ''}import PostHog
                                    import UIKit

                                    class AppDelegate: NSObject, UIApplicationDelegate {
                                        func application(_: UIApplication, didFinishLaunchingWithOptions _: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
                                            let POSTHOG_API_KEY = "<ph_project_token>"
                                            let POSTHOG_HOST = "<ph_client_api_host>"

                                            let config = PostHogConfig(apiKey: POSTHOG_API_KEY, host: POSTHOG_HOST)
                                            PostHogSDK.shared.setup(config)

                                            return true
                                        }
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Once installed, PostHog will automatically start capturing events. You can also manually send
                        events to test your integration:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Swift',
                                code: dedent`
                                    PostHogSDK.shared.capture("button_clicked", properties: ["button_name": "signup"])
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const IOSInstallation = createInstallation(getIOSSteps)
