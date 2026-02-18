import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getFlutterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

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
                    <CalloutBox type="fyi" title="SDK version">
                        <Markdown>
                            Session replay requires PostHog Flutter SDK version 4.7.0 or higher. We recommend always
                            using the latest version.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Disable auto-init for Android',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        For session replay, you need to use manual initialization. Add this to your
                        `AndroidManifest.xml` to disable auto-init:
                    </Markdown>
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
                                        <meta-data android:name="com.posthog.posthog.AUTO_INIT" android:value="false" />
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
            title: 'Disable auto-init for iOS',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add this to your `Info.plist` to disable auto-init:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'xml',
                                file: 'ios/Runner/Info.plist',
                                code: dedent`
                                    <dict>
                                        [...]
                                        <key>com.posthog.posthog.AUTO_INIT</key>
                                        <false/>
                                        [...]
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
            title: 'Enable session recordings in project settings',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your PostHog [Project Settings](https://us.posthog.com/settings/project-replay) and enable
                        **Record user sessions**. Session recordings will not work without this setting enabled.
                    </Markdown>
                    <Markdown>
                        If you're using Flutter Web, also enable the **Canvas capture** setting. This is required as
                        Flutter renders your app using a browser canvas element.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Initialize PostHog with session replay',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog in your `main.dart` with session replay enabled. Here are all the available
                        options:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'dart',
                                file: 'main.dart',
                                code: dedent`
                                    import 'package:flutter/material.dart';
                                    import 'package:posthog_flutter/posthog_flutter.dart';

                                    Future<void> main() async {
                                      WidgetsFlutterBinding.ensureInitialized();

                                      final config = PostHogConfig('<ph_project_api_key>');
                                      config.host = '<ph_client_api_host>';
                                      config.debug = true;
                                      config.captureApplicationLifecycleEvents = true;

                                      // Enable session recording. Requires enabling in your project settings as well.
                                      // Default is false.
                                      config.sessionReplay = true;

                                      // Enable masking of all text and text input fields. Default is true.
                                      config.sessionReplayConfig.maskAllTexts = false;

                                      // Enable masking of all images. Default is true.
                                      config.sessionReplayConfig.maskAllImages = false;

                                      // Throttling delay used to reduce the number of snapshots captured. Default is 1s.
                                      config.sessionReplayConfig.throttleDelay = const Duration(milliseconds: 1000);

                                      await Posthog().setup(config);
                                      runApp(MyApp());
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        For more configuration options, see the [Flutter session replay
                        docs](https://posthog.com/docs/session-replay/installation?tab=Flutter).
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Wrap your app with PostHogWidget',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        For Session Replay to work, wrap your app with `PostHogWidget` and add the `PosthogObserver`:
                    </Markdown>
                    <Tab.Group tabs={['MaterialApp', 'go_router']}>
                        <Tab.List>
                            <Tab>MaterialApp</Tab>
                            <Tab>go_router</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'dart',
                                            file: 'MyApp.dart',
                                            code: dedent`
                                                import 'package:flutter/material.dart';
                                                import 'package:posthog_flutter/posthog_flutter.dart';

                                                class MyApp extends StatelessWidget {
                                                  @override
                                                  Widget build(BuildContext context) {
                                                    return PostHogWidget(
                                                      child: MaterialApp(
                                                        navigatorObservers: [PosthogObserver()],
                                                        title: 'My App',
                                                        home: const HomeScreen(),
                                                      ),
                                                    );
                                                  }
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'dart',
                                            file: 'MyApp.dart',
                                            code: dedent`
                                                import 'package:flutter/material.dart';
                                                import 'package:go_router/go_router.dart';
                                                import 'package:posthog_flutter/posthog_flutter.dart';

                                                final GoRouter _router = GoRouter(
                                                  observers: [PosthogObserver()],
                                                  routes: [
                                                    GoRoute(
                                                      name: 'home',  // Name your routes for proper screen tracking
                                                      path: '/',
                                                      builder: (context, state) => const HomeScreen(),
                                                    ),
                                                  ],
                                                );

                                                class MyApp extends StatelessWidget {
                                                  @override
                                                  Widget build(BuildContext context) {
                                                    return PostHogWidget(
                                                      child: MaterialApp.router(
                                                        routerConfig: _router,
                                                        title: 'My App',
                                                      ),
                                                    );
                                                  }
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
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

export const FlutterInstallation = createInstallation(getFlutterSteps)
