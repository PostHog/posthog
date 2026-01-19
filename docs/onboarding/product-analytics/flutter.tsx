import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getFlutterSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
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
            title: 'Web setup',
            content: (
                <>
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
                                                !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
                                                posthog.init('<ph_project_api_key>', {
                                                    api_host: '<ph_client_api_host>',
                                                    defaults: '2025-11-30',
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
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getFlutterSteps(CodeBlock, Markdown, dedent)

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
