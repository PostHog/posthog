import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useJsSnippet } from 'lib/components/JSSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export interface FlutterSetupProps {
    includeReplay?: boolean
    includeSurveys?: boolean
    requiresManualInstall?: boolean
}

export interface FlutterInstallProps {
    apiToken?: string
}

function FlutterInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.YAML}>posthog_flutter: ^5.0.0</CodeSnippet>
}

function FlutterDartSetup(props: FlutterSetupProps & FlutterInstallProps): JSX.Element {
    const configOptions = [
        props.includeReplay &&
            `// check https://posthog.com/docs/session-replay/installation?tab=Flutter
  // for more config and to learn about how we capture sessions on mobile
  // and what to expect
  config.sessionReplay = true;
  // choose whether to mask images or text
  config.sessionReplayConfig.maskAllTexts = false;
  config.sessionReplayConfig.maskAllImages = false;`,
        props.includeSurveys && `config.surveys = true`,
    ]
        .filter(Boolean)
        .join('\n')

    return (
        <CodeSnippet language={Language.Dart}>
            {`import 'package:flutter/material.dart';

import 'package:posthog_flutter/posthog_flutter.dart';

Future<void> main() async {
  // init WidgetsFlutterBinding if not yet
  WidgetsFlutterBinding.ensureInitialized();
  final config = PostHogConfig('${props.apiToken}');
  config.host = '${apiHostOrigin()}';
  config.debug = true;
  config.captureApplicationLifecycleEvents = true;
  ${configOptions}
  // Setup PostHog with the given Context and Config
  await Posthog().setup(config);
  runApp(MyApp());
}`}
        </CodeSnippet>
    )
}

function InstallFlutterWidgetsAndObsserver(): JSX.Element {
    return (
        <CodeSnippet language={Language.Dart}>
            {`import 'package:flutter/material.dart';

import 'package:posthog_flutter/posthog_flutter.dart';

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  @override
  void initState() {
    super.initState();
  }

  @override
  Widget build(BuildContext context) {
    // Wrap your App with PostHogWidget
    return PostHogWidget(
      child: MaterialApp(
        // Add PosthogObserver to your navigatorObservers
        navigatorObservers: [PosthogObserver()],
        title: 'My App',
        home: const HomeScreen(),
      ),
    );
  }
}
// If you're using go_router, check this page to learn how to set up the PosthogObserver
// https://posthog.com/docs/libraries/flutter#capturing-screen-views`}
        </CodeSnippet>
    )
}

function InstallFlutterObserver(): JSX.Element {
    return (
        <CodeSnippet language={Language.Dart}>
            {`import 'package:flutter/material.dart';

import 'package:posthog_flutter/posthog_flutter.dart';

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  @override
  void initState() {
    super.initState();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
        // Add PosthogObserver to your navigatorObservers
        navigatorObservers: [PosthogObserver()],
        title: 'My App',
        home: const HomeScreen(),
    );
);
  }
}
// If you're using go_router, check this page to learn how to set up the PosthogObserver
// https://posthog.com/docs/libraries/flutter#capturing-screen-views

`}
        </CodeSnippet>
    )
}

function FlutterAndroidSetupSnippet({ requiresManualInstall }: FlutterSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    const minSdkVersionInstructions = (
        <>
            <p>
                Update the minimum Android SDK version to <strong>21</strong> in{' '}
                <strong>android/app/build.gradle</strong>:
            </p>
            <CodeSnippet language={Language.Groovy}>
                {`defaultConfig {
    minSdkVersion 21
    // rest of your config
}`}
            </CodeSnippet>
        </>
    )

    if (requiresManualInstall) {
        return (
            <>
                <CodeSnippet language={Language.XML}>
                    {
                        '<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.AUTO_INIT" android:value="false" />\n</application>'
                    }
                </CodeSnippet>
                {minSdkVersionInstructions}
            </>
        )
    }
    return (
        <>
            <CodeSnippet language={Language.XML}>
                {'<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.API_KEY" android:value="' +
                    currentTeam?.api_token +
                    '" />\n\t<meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="' +
                    url +
                    '" />\n\t<meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="true" />\n\t<meta-data android:name="com.posthog.posthog.DEBUG" android:value="true" />\n</application>'}
            </CodeSnippet>
            {minSdkVersionInstructions}
        </>
    )
}

function FlutterIOSSetupSnippet({ requiresManualInstall }: FlutterSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    const minPlatformVersionInstructions = (
        <>
            <p>
                Update the minimum platform version to iOS <strong>13.0</strong> in your <strong>Podfile</strong>:
            </p>
            <CodeSnippet language={Language.YAML}>
                {`platform :ios, '13.0'
    # rest of your config`}
            </CodeSnippet>
        </>
    )

    if (requiresManualInstall) {
        return (
            <>
                <CodeSnippet language={Language.XML}>
                    {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.AUTO_INIT</key>\n\t<false/>\n\t[...]\n</dict>'}
                </CodeSnippet>
                {minPlatformVersionInstructions}
            </>
        )
    }
    return (
        <>
            <CodeSnippet language={Language.XML}>
                {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.API_KEY</key>\n\t<string>' +
                    currentTeam?.api_token +
                    '</string>\n\t<key>com.posthog.posthog.POSTHOG_HOST</key>\n\t<string>' +
                    url +
                    '</string>\n\t<key>com.posthog.posthog.CAPTURE_APPLICATION_LIFECYCLE_EVENTS</key>\n\t<true/>\n\t<key>com.posthog.posthog.DEBUG</key>\n\t<true/>\n</dict>'}
            </CodeSnippet>
            {minPlatformVersionInstructions}
        </>
    )
}

function FlutterWebSetupSnippet(): JSX.Element {
    const jsSnippet = useJsSnippet(4)

    return (
        <CodeSnippet language={Language.HTML}>
            {`<!DOCTYPE html>
<html>
  <head>
    ...
${jsSnippet}
  </head>
</html>`}
        </CodeSnippet>
    )
}

export function SDKInstallFlutterInstructions(props: FlutterSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <FlutterInstallSnippet />
            <h3>Android Setup</h3>
            <p className="prompt-text">Add these values in AndroidManifest.xml</p>
            <FlutterAndroidSetupSnippet {...props} />
            <h3>iOS/macOS Setup</h3>
            <p className="prompt-text">Add these values in Info.plist</p>
            <FlutterIOSSetupSnippet {...props} />
            {props.requiresManualInstall && (
                <>
                    <h3>Dart Setup</h3>
                    <p className="prompt-text">Add these values in main.dart</p>
                    <FlutterDartSetup {...props} apiToken={currentTeam?.api_token} />
                    {props.includeSurveys && (
                        <>
                            <p className="prompt-text">
                                Install the <strong>PosthogObserver</strong> to your app
                            </p>
                            <InstallFlutterObserver />
                        </>
                    )}
                    {props.includeReplay && (
                        <>
                            <p className="prompt-text">
                                Wrap your app with the <strong>PostHogWidget</strong> and install the{' '}
                                <strong>PosthogObserver</strong>
                            </p>
                            <InstallFlutterWidgetsAndObsserver />
                        </>
                    )}
                </>
            )}
            <h3>Web Setup</h3>
            <p className="prompt-text">Add these values in index.html</p>
            <FlutterWebSetupSnippet />
        </>
    )
}

export function SDKInstallFlutterTrackScreenInstructions(): JSX.Element {
    return (
        <>
            <p>
                With the <Link to="https://posthog.com/docs/libraries/flutter#example">PosthogObserver</Link> Observer,
                PostHog will try to record all screen changes automatically.
            </p>
            <p>
                If you want to manually send a new screen capture event, use the <code>screen</code> function.
            </p>
            <CodeSnippet language={Language.Dart}>{`import 'package:posthog_flutter/posthog_flutter.dart';

await Posthog().screen(
    screenName: 'Dashboard',
    properties: {
      'background': 'blue',
      'hero': 'superhog'
    });
`}</CodeSnippet>
        </>
    )
}
