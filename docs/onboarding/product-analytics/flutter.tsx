import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getFlutterInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Tab, dedent } = ctx

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add the PostHog Flutter SDK to your `pubspec.yaml`:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'yaml',
                                file: 'pubspec.yaml',
                                code: dedent`
                                    posthog_flutter: ^5.24.0
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Platform setup',
            badge: 'required',
            content: (
                <Tab.Group tabs={['Android', 'iOS/macOS', 'Web']}>
                    <Tab.Panels>
                        <Tab.Panel>
                            <Markdown>Add these values to your `AndroidManifest.xml`:</Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'xml',
                                        file: 'android/app/src/main/AndroidManifest.xml',
                                        code: dedent`
                                          <application>
                                            <activity>
                                              [...]
                                            </activity>
                                            <meta-data android:name="com.posthog.posthog.PROJECT_TOKEN" android:value="<ph_project_token>" />
                                            <meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="<ph_client_api_host>" />
                                            <meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="true" />
                                            <meta-data android:name="com.posthog.posthog.DEBUG" android:value="true" />
                                          </application>
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                Update the minimum Android SDK version to **21** in `android/app/build.gradle`:
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'groovy',
                                        file: 'android/app/build.gradle',
                                        code: dedent`
                                          defaultConfig {
                                            minSdkVersion 23
                                            // rest of your config
                                          }
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>Add these values to your `Info.plist`:</Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'xml',
                                        file: 'ios/Runner/Info.plist',
                                        code: dedent`
                                          <dict>
                                            [...]
                                            <key>com.posthog.posthog.PROJECT_TOKEN</key>
                                            <string><ph_project_token></string>
                                            <key>com.posthog.posthog.POSTHOG_HOST</key>
                                            <string><ph_client_api_host></string>
                                            <key>com.posthog.posthog.CAPTURE_APPLICATION_LIFECYCLE_EVENTS</key>
                                            <true/>
                                            <key>com.posthog.posthog.DEBUG</key>
                                            <true/>
                                          </dict>
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>Update the minimum platform version to iOS 13.0 in your `Podfile`:</Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'ruby',
                                        file: 'Podfile',
                                        code: dedent`
                                          platform :ios, '13.0'
                                          # rest of your config
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>Add these values in `index.html`:</Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'html',
                                        file: 'web/index.html',
                                        code: dedent`
                                          <!DOCTYPE html>
                                          <html>
                                            <head>
                                              ...
                                              <script>
                                                ${snippetFunctions(DEFAULT_SNIPPET_METHODS)}
                                                posthog.init('<ph_project_token>', {
                                                    api_host: '<ph_client_api_host>',
                                                    defaults: '${SDK_DEFAULTS_DATE}',
                                                })
                                              </script>
                                            </head>
                                            <body>
                                              ...
                                            </body>
                                          </html>
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
            ),
        },
    ]
}

export const getFlutterEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
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
                            language: 'dart',
                            file: 'Dart',
                            code: dedent`
                                    import 'package:posthog_flutter/posthog_flutter.dart';

                                    await Posthog().capture(
                                        eventName: 'button_clicked',
                                        properties: {
                                          'button_name': 'signup'
                                        }
                                    );
                                `,
                        },
                    ]}
                />
            </>
        ),
    }
}

export const getFlutterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getFlutterInstallSteps(ctx),
    getFlutterEventStep(ctx),
]

export const FlutterInstallation = createInstallation(getFlutterSteps)
