import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getIOSInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Install dependency',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install via Swift Package Manager. PostHog requires Xcode 26 or later, and iOS 15, macOS 11,
                        tvOS 15, watchOS 10, or visionOS 1 or later.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Package.swift',
                                code: dedent`
                                    dependencies: [
                                      .package(url: "https://github.com/PostHog/posthog-ios.git", from: "4.0.0")
                                    ]
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="Using CocoaPods?">
                        <Markdown>
                            {
                                'Version 4 is only published to Swift Package Manager. Version 3 stays on CocoaPods (`pod "PostHog", "~> 3.0"`), but [CocoaPods trunk becomes read-only on December 2, 2026](https://blog.cocoapods.org/CocoaPods-Specs-Repo/). After that, existing 3.x versions stay installable, but new releases only ship through Swift Package Manager. To switch, see the [iOS migration guide](https://posthog.com/docs/libraries/ios/migration).'
                            }
                        </Markdown>
                    </CalloutBox>
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
                                    import PostHog
                                    import UIKit

                                    class AppDelegate: NSObject, UIApplicationDelegate {
                                        func application(_: UIApplication, didFinishLaunchingWithOptions _: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
                                            let POSTHOG_PROJECT_TOKEN = "<ph_project_token>"
                                            let POSTHOG_HOST = "<ph_client_api_host>"

                                            let config = PostHogConfig(projectToken: POSTHOG_PROJECT_TOKEN, host: POSTHOG_HOST)
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
    ]
}

export const getIOSEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
        title: 'Send events',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    Once installed, PostHog will automatically start capturing events. You can also manually send events
                    to test your integration:
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
    }
}

export const getIOSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getIOSInstallSteps(ctx),
    getIOSEventStep(ctx),
]

export const IOSInstallation = createInstallation(getIOSSteps)
