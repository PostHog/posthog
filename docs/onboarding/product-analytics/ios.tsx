import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getIOSSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
): StepDefinition[] => {
    return [
        {
            title: 'Install the SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>You can install PostHog via CocoaPods by adding it to your Podfile:</Markdown>
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
                    <Markdown>Or install via Swift Package Manager and add PostHog to the dependencies section of your Package.swift file:</Markdown>
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
                    <Markdown>
                        Then add it as a dependency for your target:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'Package.swift',
                                code: dedent`
                                    .target(
                                        name: "myApp",
                                        dependencies: [.product(name: "PostHog", package: "posthog-ios")]),
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
                    <Markdown>Configuration is done through the PostHogConfig object.</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'UIKit',
                                code: dedent`
                                    import Foundation
                                    import PostHog
                                    import UIKit

                                    class AppDelegate: NSObject, UIApplicationDelegate {
                                        func application(_: UIApplication, didFinishLaunchingWithOptions _: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
                                            let POSTHOG_API_KEY = "<ph_project_api_key>"
                                            let POSTHOG_HOST = "<ph_client_api_host>"

                                            let config = PostHogConfig(apiKey: POSTHOG_API_KEY, host: POSTHOG_HOST)
                                            PostHogSDK.shared.setup(config)

                                            return true
                                        }
                                    }
                                `,
                            },
                            {
                                language: 'swift',
                                file: 'SwiftUI',
                                code: dedent`
                                    import SwiftUI
                                    import PostHog

                                    @main
                                    struct YourGreatApp: App {
                                        // Add PostHog to your app's initializer.
                                        // If using UIApplicationDelegateAdaptor, see the UIKit tab.
                                        init() {
                                            let POSTHOG_API_KEY = "<ph_project_api_key>"
                                            let POSTHOG_HOST = "<ph_client_api_host>"

                                            let config = PostHogConfig(apiKey: POSTHOG_API_KEY, host: POSTHOG_HOST)
                                            PostHogSDK.shared.setup(config)
                                        }
                                        
                                        var body: some Scene {
                                            WindowGroup {
                                                ContentView()
                                            }
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
                    <PersonProfiles language="swift" />
                </>
            ),
        },
    ]
}

export const IOSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getIOSSteps(CodeBlock, Markdown, dedent)

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}
