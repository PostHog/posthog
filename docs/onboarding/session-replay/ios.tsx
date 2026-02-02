import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getIOSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent, snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return [
        {
            title: 'Install the SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add PostHog to your Podfile:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'ruby',
                                file: 'Podfile',
                                code: dedent`
                                    pod "PostHog", "~> 3.0"
                                `,
                            },
                        ]}
                    />
                    <Markdown>Or install via Swift Package Manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Package.swift',
                                code: dedent`
                                    dependencies: [
                                      .package(url: "https://github.com/PostHog/posthog-ios.git", from: "3.0.0")
                                    ]
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="SDK version">
                        <Markdown>
                            Session replay requires PostHog iOS SDK version 3.6.0 or higher. We recommend always using
                            the latest version.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Enable session recordings in project settings',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your PostHog [Project Settings](https://us.posthog.com/settings/project-replay) and enable
                        **Record user sessions**. Session recordings will not work without this setting enabled.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure PostHog with session replay',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Add `sessionReplay = true` to your PostHog configuration. Here are all the available options:
                    </Markdown>
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
                                            let POSTHOG_API_KEY = "<ph_project_api_key>"
                                            let POSTHOG_HOST = "<ph_client_api_host>"

                                            let config = PostHogConfig(apiKey: POSTHOG_API_KEY, host: POSTHOG_HOST)

                                            // Enable session recording. Requires enabling in your project settings as well.
                                            // Default is false.
                                            config.sessionReplay = true

                                            // Whether text and text input fields are masked. Default is true.
                                            // Password inputs are always masked regardless
                                            config.sessionReplayConfig.maskAllTextInputs = true

                                            // Whether images are masked. Default is true.
                                            config.sessionReplayConfig.maskAllImages = true

                                            // Whether network requests are captured in recordings. Default is true
                                            // Only metric-like data like speed, size, and response code are captured.
                                            // No data is captured from the request or response body.
                                            config.sessionReplayConfig.captureNetworkTelemetry = true

                                            // Whether replays are created using high quality screenshots. Default is false.
                                            // Required for SwiftUI.
                                            // If disabled, replays are created using wireframes instead.
                                            // The screenshot may contain sensitive information, so use with caution
                                            config.sessionReplayConfig.screenshotMode = true

                                            PostHogSDK.shared.setup(config)

                                            return true
                                        }
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        For more configuration options, see the [iOS session replay
                        docs](https://posthog.com/docs/session-replay/installation?tab=iOS).
                    </Markdown>
                    <CalloutBox type="fyi" title="SwiftUI support">
                        <Markdown>
                            SwiftUI is only supported if the `screenshotMode` option is enabled. Custom views and
                            WebViews also require screenshot mode for full support.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Watch session recordings',
            badge: 'recommended',
            content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
        },
    ]
}

export const IOSInstallation = createInstallation(getIOSSteps)
