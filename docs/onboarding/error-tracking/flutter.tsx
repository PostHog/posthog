import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getFlutterSteps as getFlutterStepsPA } from '../product-analytics/flutter'
import { StepDefinition } from '../steps'

const FLUTTER_ERROR_TRACKING_MIN_VERSION = '5.58.0'

export const getFlutterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const installSteps = getFlutterStepsPA(ctx, { minVersion: FLUTTER_ERROR_TRACKING_MIN_VERSION })

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
                        Dart AOT symbolication and background isolate listeners require \`posthog_flutter\` ${FLUTTER_ERROR_TRACKING_MIN_VERSION} or later. If your project uses an earlier version, set \`posthog_flutter: ^${FLUTTER_ERROR_TRACKING_MIN_VERSION}\` in \`pubspec.yaml\` and run \`flutter pub get\`.
                    `}
                </Markdown>
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
                              final config = PostHogConfig('<ph_project_token>');
                              // Enable exception autocapture
                              config.errorTrackingConfig.captureFlutterErrors = true;
                              config.errorTrackingConfig.capturePlatformDispatcherErrors = true;
                              config.errorTrackingConfig.captureIsolateErrors = true;
                              // Requires SDK version 5.22.0 or higher
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
                        | \`captureFlutterErrors\` | Captures Flutter framework errors (\`FlutterError.onError\`) |
                        | \`capturePlatformDispatcherErrors\` | Captures Dart runtime errors (\`PlatformDispatcher.onError\`). Web not supported. |
                        | \`captureIsolateErrors\` | Captures errors from the isolate where PostHog is set up. Spawn background isolates paused and call \`isolate.addPostHogErrorListener()\` before resuming them to capture their errors. Web not supported. |
                        | \`captureNativeExceptions\` | Captures native exceptions. Android (Java/Kotlin) and Apple platforms (iOS, macOS, tvOS). |
                        | \`captureSilentFlutterErrors\` | Captures Flutter errors that are marked as silent. Default: false. |
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
                              final config = PostHogConfig('<ph_project_token>');
                              // Configure error tracking
                              config.errorTrackingConfig.inAppIncludes.add('package:your_app');
                              config.errorTrackingConfig.inAppExcludes.add('package:third_party_lib');
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

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/events)
                `}
            </Markdown>
        ),
    }

    const uploadSymbolsStep: StepDefinition = {
        title: 'Upload Dart debug symbols',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Flutter writes Dart debug symbols for release builds when you pass \`--split-debug-info\`. Upload the symbols for each build you ship so PostHog can show Dart function names and line numbers for Android and iOS exceptions. Add \`--obfuscate\` to the build command if you obfuscate your app.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Android',
                            code: dedent`
                              flutter build apk --release \\
                                --split-debug-info=build/posthog-symbols/android
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'iOS',
                            code: dedent`
                              flutter build ipa --release \\
                                --split-debug-info=build/posthog-symbols/ios
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Run these commands from your app's root directory to upload each build's \`.symbols\` files. Sign in with \`posthog-cli login\`, or set \`POSTHOG_CLI_API_KEY\` and \`POSTHOG_CLI_PROJECT_ID\` in CI. Keep each build's symbols in its own directory.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Android',
                            code: dedent`
                              posthog-cli symbol-sets upload \\
                                --directory build/posthog-symbols/android
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'iOS',
                            code: dedent`
                              posthog-cli symbol-sets upload \\
                                --directory build/posthog-symbols/ios
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        To show [source code context](https://posthog.com/docs/error-tracking/stack-traces), use this command instead of the symbol-only upload. It includes your app's source files:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Android',
                            code: dedent`
                              posthog-cli symbol-sets upload \\
                                --directory build/posthog-symbols/android \\
                                --include-source --source-root ./lib
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'iOS',
                            code: dedent`
                              posthog-cli symbol-sets upload \\
                                --directory build/posthog-symbols/ios \\
                                --include-source --source-root ./lib
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        \`--source-root ./lib\` limits source files, not symbol files. Run the upload on the build machine while your app source is available. Review your source files before uploading them. See the [CLI debug symbol guide](https://github.com/PostHog/posthog/blob/master/cli/README.md#uploading-native-debug-symbols) for more options.
                    `}
                </Markdown>
            </>
        ),
    }

    const futureFeaturesStep: StepDefinition = {
        title: 'Future features',
        badge: 'optional',
        content: (
            <Markdown>
                {dedent`
                    We currently don't support the following features:

                    - Restoring obfuscated Dart exception class names
                    - Capturing native C/C++ exceptions on Android (Java/Kotlin only)

                    For symbolicated native Android and iOS stack traces, see the [Flutter debug symbols guide](https://posthog.com/docs/error-tracking/upload-source-maps/flutter).
                `}
            </Markdown>
        ),
    }

    return [
        ...installSteps,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
        uploadSymbolsStep,
        futureFeaturesStep,
    ]
}

export const FlutterInstallation = createInstallation(getFlutterSteps)
