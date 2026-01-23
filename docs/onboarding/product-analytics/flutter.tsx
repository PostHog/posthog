import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getFlutterSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    Tab: any,
    dedent: any,
    snippets: any
): StepDefinition[] => {
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
                                    posthog_flutter: ^5.0.0
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Android setup',
            badge: 'required',
            content: (
                <>
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
                                        <meta-data android:name="com.posthog.posthog.API_KEY" android:value="<ph_project_api_key>" />
                                        <meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="<ph_client_api_host>" />
                                        <meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="true" />
                                        <meta-data android:name="com.posthog.posthog.DEBUG" android:value="true" />
                                    </application>
                                `,
                            },
                        ]}
                    />
                    <Markdown>Update the minimum Android SDK version to **21** in `android/app/build.gradle`:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'groovy',
                                file: 'android/app/build.gradle',
                                code: dedent`
                                    defaultConfig {
                                        minSdkVersion 21
                                        // rest of your config
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'iOS/macOS setup',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add these values to your `Info.plist`:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'xml',
                                file: 'ios/Runner/Info.plist',
                                code: dedent`
                                    <dict>
                                        [...]
                                        <key>com.posthog.posthog.API_KEY</key>
                                        <string><ph_project_api_key></string>
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
                </>
            ),
        },
        {
            title: 'Dart setup',
            content: (
                <>
                    <Markdown>Then setup the SDK manually:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'dart',
                                file: 'Dart',
                                code: dedent`
                                    import 'package:flutter/material.dart';
                                    import 'package:posthog_flutter/posthog_flutter.dart';

                                    Future<void> main() async {
                                        // init WidgetsFlutterBinding if not yet
                                        WidgetsFlutterBinding.ensureInitialized();
                                        final config = PostHogConfig('<ph_project_api_key>');
                                        config.debug = true;
                                        config.captureApplicationLifecycleEvents = true;
                                        config.host = '<ph_client_api_host>';
                                        await Posthog().setup(config);
                                        runApp(MyApp());
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
                    <PersonProfiles language="dart" />
                </>
            ),
        },
    ]
}

export const FlutterInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = useMDXComponents()
    const steps = getFlutterSteps(CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets)

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
