import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getIOSSteps as getIOSStepsPA } from '../product-analytics/ios'
import { StepDefinition } from '../steps'

export const getIOSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const installSteps = getIOSStepsPA(ctx, {
        minVersionPod: '3.56',
        minVersionSPM: '3.56.0',
    })

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <CalloutBox type="fyi" title="Remote configuration">
                    <Markdown>
                        {dedent`
                            Exception autocapture can also be managed remotely via the 
                            [error tracking settings](https://app.posthog.com/settings/project-error-tracking#exception-autocapture).
                        `}
                    </Markdown>
                </CalloutBox>
                <CalloutBox type="fyi" title="Platform support">
                    <Markdown>
                        {dedent`
                            Exception autocapture is available on **iOS, macOS, and tvOS** only. 
                            It is not available on watchOS or visionOS due to platform limitations.
                            
                            You can still capture events manually on all platforms, including visionOS.
                        `}
                    </Markdown>
                </CalloutBox>
                <Markdown>
                    {dedent`
                        You can autocapture exceptions by setting the \`errorTrackingConfig.autoCapture\` 
                        argument to \`true\` when initializing the PostHog SDK.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'swift',
                            file: 'Swift',
                            code: dedent`
                              import PostHog

                              let config = PostHogConfig(
                                  projectToken: "<ph_project_token>",
                                  host: "<ph_client_api_host>"
                              )
                              config.errorTrackingConfig.autoCapture = true
                              
                              PostHogSDK.shared.setup(config)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        When enabled, this automatically captures \`$exception\` events for:
                        
                        - **Mach exceptions** (e.g., \`EXC_BAD_ACCESS\`, \`EXC_CRASH\`)
                        - **POSIX signals** (e.g., \`SIGSEGV\`, \`SIGABRT\`, \`SIGBUS\`)
                        - **Uncaught NSExceptions**
                        
                        Crashes are persisted to disk and sent as \`$exception\` events with level "fatal" on the next app launch.
                    `}
                </Markdown>
            </>
        ),
    }

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        ### Swift Error handling
                        
                        You can manually capture exceptions using the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'swift',
                            file: 'Swift',
                            code: dedent`
                              import PostHog

                              do {
                                  try FileManager.default.removeItem(at: badFileUrl)
                              } catch {
                                  PostHogSDK.shared.captureException(error)
                              }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        ### Objective-C NSException handling
                        
                        For Objective-C code that uses NSException:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'objc',
                            file: 'Objective-C',
                            code: dedent`
                              @import PostHog;

                              @try {
                                  [self riskyOperation];
                              } @catch (NSException *exception) {
                                  [[PostHogSDK shared] captureExceptionWithNSException:exception properties:nil];
                              }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        ### Adding custom properties
                        
                        You can add custom properties to help with debugging, grouping, and analysis:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'swift',
                            file: 'Swift',
                            code: dedent`
                              do {
                                  try performNetworkRequest()
                              } catch {
                                  PostHogSDK.shared.captureException(error, properties: [
                                      "endpoint": "/api/users",
                                      "retry_count": 3
                                  ])
                              }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        This is helpful if you've built your own error handling logic or want to capture exceptions that are handled by your application code.
                    `}
                </Markdown>
            </>
        ),
    }

    const inAppConfigStep: StepDefinition = {
        title: 'Configure in-app frames',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        By default, PostHog automatically marks your app's code as "in-app" in stack traces to help you focus on your code rather than system frameworks.
                        
                        You can customize this behavior with \`errorTrackingConfig\`:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'swift',
                            file: 'Swift',
                            code: dedent`
                              import PostHog

                              let config = PostHogConfig(
                                  projectToken: "<ph_project_token>",
                                  host: "<ph_client_api_host>"
                              )
                              
                              // Mark additional packages as in-app
                              config.errorTrackingConfig.inAppIncludes = [
                                  "MySharedFramework",
                                  "MyUtilityLib"
                              ]
                              
                              // Exclude specific packages from being marked as in-app
                              config.errorTrackingConfig.inAppExcludes = [
                                  "Alamofire",
                                  "SDWebImage"
                              ]
                              
                              // Control default behavior for unknown packages
                              config.errorTrackingConfig.inAppByDefault = true // default
                              
                              PostHogSDK.shared.setup(config)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        **Configuration options:**
                        
                        | Option | Description |
                        | --- | --- |
                        | \`inAppIncludes\` | List of package/bundle identifiers to mark as in-app (takes precedence over excludes) |
                        | \`inAppExcludes\` | List of package/bundle identifiers to exclude from in-app |
                        | \`inAppByDefault\` | Whether frames are considered in-app by default when origin cannot be determined |
                        
                        **Default behavior:**
                        - Your app's bundle identifier and executable name are automatically included
                        - System frameworks (Foundation, UIKit, etc.) are automatically excluded
                    `}
                </Markdown>
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Before proceeding, let's make sure exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, exceptionAutocaptureStep, manualCaptureStep, inAppConfigStep, verifyStep]
}

export const IOSInstallation = createInstallation(getIOSSteps)
