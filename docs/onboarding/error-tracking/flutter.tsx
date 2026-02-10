import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFlutterSteps as getFlutterStepsPA } from '../product-analytics/flutter'
import { StepDefinition } from '../steps'

export const getFlutterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const installSteps = getFlutterStepsPA(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <CalloutBox type="fyi" title="Client-side configuration only">
                    <Markdown>
                        {dedent`
                            This configuration is client-side only. Support for remote configuration in the [error tracking settings](https://app.posthog.com/settings/project-error-tracking#exception-autocapture) will be added in a future release.
                        `}
                    </Markdown>
                </CalloutBox>
                <Markdown>
                    {dedent`
                        You can autocapture exceptions by configuring the \`errorTrackingConfig\` when setting up PostHog:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'dart',
                            file: 'Dart',
                            code: dedent`
                              final config = PostHogConfig('<ph_project_api_key>');
                              // Enable exception autocapture
                              config.errorTrackingConfig.captureFlutterErrors = true;
                              config.errorTrackingConfig.capturePlatformDispatcherErrors = true;
                              config.errorTrackingConfig.captureIsolateErrors = true;
                              config.errorTrackingConfig.captureNativeExceptions = true;
                              config.errorTrackingConfig.captureSilentFlutterErrors = false;
                              await Posthog().setup(config);
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        **Configuration options:**

                        | Option | Description |
                        | --- | --- |
                        | \`captureFlutterErrors\` | Captures Flutter framework errors (FlutterError.onError) |
                        | \`capturePlatformDispatcherErrors\` | Captures Dart runtime errors (PlatformDispatcher.onError) // Web not supported |
                        | \`captureIsolateErrors\` | Captures errors from main isolate // Web not supported |
                        | \`captureNativeExceptions\` | Captures native exceptions (Java/Kotlin exceptions) // Android only |
                        | \`captureSilentFlutterErrors\` | Captures Flutter errors that are marked as silent (default: false) |
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
                        ### Basic usage

                        You can manually capture exceptions using the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'dart',
                            file: 'Dart',
                            code: dedent`
                              try {
                                // Your awesome code that may throw
                                await someRiskyOperation();
                              } catch (exception, stackTrace) {
                                // Capture the exception with PostHog
                                await Posthog().captureException(
                                  error: exception,
                                  stackTrace: stackTrace,
                                  properties: {
                                    'user_action': 'button_press',
                                    'feature_name': 'data_sync',
                                  },
                                );
                              }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        This is helpful if you've built your own error handling logic or want to capture exceptions that are handled by your application code.

                        ### Error tracking configuration

                        You can configure error tracking behavior when setting up PostHog:
                    `}
                </Markdown>
                <CalloutBox type="fyi" title="Flutter web apps use minified stack trace frames">
                    <Markdown>
                        {dedent`
                            Flutter web apps generate minified stack trace frames by default, which may cause the configurations below to behave differently or not work as expected.
                        `}
                    </Markdown>
                </CalloutBox>
                <CodeBlock
                    blocks={[
                        {
                            language: 'dart',
                            file: 'Dart',
                            code: dedent`
                              final config = PostHogConfig('<ph_project_api_key>');
                              // Configure error tracking
                              config.errorTrackingConfig.inAppIncludes = ['package:your_app'];
                              config.errorTrackingConfig.inAppExcludes = ['package:third_party_lib'];
                              config.errorTrackingConfig.inAppByDefault = true;
                              await Posthog().setup(config);
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        **Configuration options:**

                        | Option | Description |
                        | --- | --- |
                        | \`inAppIncludes\` | List of package names to be considered inApp frames (takes precedence over excludes) |
                        | \`inAppExcludes\` | List of package names to be excluded from inApp frames |
                        | \`inAppByDefault\` | Whether frames are considered inApp by default when their origin cannot be determined |

                        \`inApp\` frames are stack trace frames that belong to your application code (as opposed to third-party libraries or system code). These are highlighted in the PostHog error tracking interface to help you focus on the relevant parts of the stack trace.
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

    const futureFeaturesStep: StepDefinition = {
        title: 'Future features',
        badge: 'optional',
        content: (
          <Markdown>
                  {dedent`
                      We currently don't support the following features:

                      - No de-obfuscating stacktraces from obfuscated builds ([\\--obfuscate](https://docs.flutter.dev/deployment/obfuscate) and [\\--split-debug-info](https://docs.flutter.dev/deployment/obfuscate)) for Dart code
                      - No de-obfuscating stacktraces when [isMinifyEnabled](https://developer.android.com/topic/performance/app-optimization/enable-app-optimization) is enabled for Java/Kotlin code
                      - No [Source code context](/docs/error-tracking/stack-traces.md) associated with an exception
                      - No native iOS exception capture
                      - No native C/C++ exception capture on Android (Java/Kotlin only)
                      - No background isolate error capture

                      These features will be added in future releases. We recommend you stay 
                      up to date with the latest version of the PostHog Flutter SDK.
                  `}
              </Markdown>
        ),
    }

    return [
        ...installSteps,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
        futureFeaturesStep,
    ]
}

export const FlutterInstallation = createInstallation(getFlutterSteps)
