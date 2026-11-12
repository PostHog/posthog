import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

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
                                'Version 4 is only published to Swift Package Manager. Version 3 stays on CocoaPods (`pod "PostHog", "~> 3.0"`), but [CocoaPods trunk becomes read-only on December 2, 2026](https://blog.cocoapods.org/CocoaPods-Specs-Repo/). After that, existing 3.x versions stay installable, but new releases only ship through Swift Package Manager. To switch, see [upgrading from version 3 to version 4](https://posthog.com/docs/libraries/ios#upgrading-from-version-3-to-version-4).'
                            }
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
                                            let POSTHOG_PROJECT_TOKEN = "<ph_project_token>"
                                            let POSTHOG_HOST = "<ph_client_api_host>"

                                            let config = PostHogConfig(projectToken: POSTHOG_PROJECT_TOKEN, host: POSTHOG_HOST)

                                            // Enable session recording. Requires enabling in your project settings as well.
                                            // Default is false.
                                            config.sessionReplay = true

                                            // Whether text and text input fields are masked. Default is true.
                                            // Password inputs are always masked regardless
                                            config.sessionReplayConfig.maskAllTextInputs = true

                                            // Whether images are masked. Default is true.
                                            config.sessionReplayConfig.maskAllImages = true

                                            // Whether logs are captured in recordings. Default is false.
                                            //
                                            // Support for remote configuration 
                                            // in the [session replay settings](https://app.posthog.com/settings/project-replay#replay-log-capture)
                                            // requires SDK version 3.41.1 or higher.
                                            config.sessionReplayConfig.captureLogs = false

                                            // Whether network requests are captured in recordings. Default is true
                                            // Only metric-like data like speed, size, and response code are captured.
                                            // No data is captured from the request or response body.
                                            //
                                            // Support for remote configuration 
                                            // in the [session replay settings](https://app.posthog.com/settings/project-replay#replay-network)
                                            // requires SDK version 3.41.1 or higher.
                                            config.sessionReplayConfig.captureNetworkTelemetry = true

                                            // Replays are recorded as masked screenshots, so mask anything sensitive.
                                            // Before SDK version 4.0, also set config.sessionReplayConfig.screenshotMode = true,
                                            // otherwise replays are recorded as wireframes and SwiftUI screens aren't recorded.

                                            // Experimental. Moves screenshot capture to a background queue, which can
                                            // reduce main-thread hangs and dropped frames on complex screens or high
                                            // refresh rate (120Hz ProMotion) displays. May trigger Xcode's Main Thread
                                            // Checker and briefly freeze the app on the first capture.
                                            // Default is false. Requires SDK version 3.58.1 or higher.
                                            config.sessionReplayConfig.screenshotModeBackgroundCapture = false

                                            // Experimental. Screenshot resolution as a fraction of the screen's native
                                            // resolution, from 0.1 to 1.0. With no value, captures one pixel per point,
                                            // which is a third of native resolution on a 3x device. Higher values give
                                            // sharper replays at the cost of capture time and upload size.
                                            // Default is nil. Requires SDK version 3.93.0 or higher.
                                            config.sessionReplayConfig.screenshotScale = nil

                                            // Minimum time (in seconds) between snapshots. Default is 1.0s.
                                            // Snapshots are taken when views lay out, so this caps how often one
                                            // can be captured rather than setting a fixed frame rate.
                                            // Lower values can make playback smoother, at the cost of more
                                            // capture work on the device.
                                            config.sessionReplayConfig.throttleDelay = 1.0

                                            // Sample rate for session recordings. A value between 0.0 and 1.0.
                                            // 1.0 means 100% of sessions will be recorded. 0.5 means 50%, and so on.
                                            // Default is nil (all sessions are recorded).
                                            // 
                                            // Support for remote configuration
                                            // in the [session replay triggers](https://us.posthog.com/settings/project-replay#replay-triggers)
                                            // requires SDK version 3.42.0 or higher.
                                            config.sessionReplayConfig.sampleRate = nil

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
                            SDK version 4.0 and later record SwiftUI, custom views and WebViews as screenshots. Earlier
                            versions only support them if the `screenshotMode` option is enabled. A `WKWebView` is
                            masked whole while `maskAllTextInputs` or `maskAllImages` is on, as in this snippet.
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
