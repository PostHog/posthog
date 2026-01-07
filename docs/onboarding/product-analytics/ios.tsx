import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const IOSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install via CocoaPods" badge="required">
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
            </Step>

            <Step title="Configure PostHog" badge="required">
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
                                        let POSTHOG_API_KEY = "<ph_project_api_key>"
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
            </Step>

            <Step title="Send events">
                <Markdown>Capture custom events using the PostHog SDK:</Markdown>
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
            </Step>
        </Steps>
    )
}
