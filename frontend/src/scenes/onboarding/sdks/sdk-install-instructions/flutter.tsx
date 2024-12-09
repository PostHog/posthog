import { LemonBanner, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useJsSnippet } from 'lib/components/JSSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export interface FlutterSetupProps {
    includeReplay?: boolean
}

export interface FlutterInstallProps {
    apiToken?: string
}

function FlutterInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.YAML}>posthog_flutter: ^4.0.0</CodeSnippet>
}

function InstallFlutterSessionReplay(props: FlutterInstallProps): JSX.Element {
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

  // check https://posthog.com/docs/session-replay/installation?tab=Flutter
  // for more config and to learn about how we capture sessions on mobile
  // and what to expect
  config.sessionReplay = true;
  // choose whether to mask images or text
  config.sessionReplayConfig.maskAllTexts = false;
  config.sessionReplayConfig.maskAllImages = false;

  // Setup PostHog with the given Context and Config
  await Posthog().setup(config);
  runApp(MyApp());
}`}
        </CodeSnippet>
    )
}

function InstallFlutterWidgetsSessionReplay(): JSX.Element {
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
}`}
        </CodeSnippet>
    )
}

function FlutterAndroidSetupSnippet({ includeReplay }: FlutterSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()
    const props = { apiToken: currentTeam?.api_token }

    if (includeReplay) {
        return (
            <>
                <CodeSnippet language={Language.XML}>
                    {
                        '<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.AUTO_INIT" android:value="false" />\n</application>'
                    }
                </CodeSnippet>
                <InstallFlutterSessionReplay {...props} />
                <InstallFlutterWidgetsSessionReplay />
            </>
        )
    }
    return (
        <CodeSnippet language={Language.XML}>
            {'<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.API_KEY" android:value="' +
                currentTeam?.api_token +
                '" />\n\t<meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="' +
                url +
                '" />\n\t<meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="true" />\n\t<meta-data android:name="com.posthog.posthog.DEBUG" android:value="true" />\n</application>'}
        </CodeSnippet>
    )
}

function FlutterIOSSetupSnippet({ includeReplay }: FlutterSetupProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()
    const props = { apiToken: currentTeam?.api_token }

    if (includeReplay) {
        return (
            <>
                <CodeSnippet language={Language.XML}>
                    {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.AUTO_INIT</key>\n\t<false/>\n\t[...]\n</dict>'}
                </CodeSnippet>
                <InstallFlutterSessionReplay {...props} />
                <InstallFlutterWidgetsSessionReplay />
            </>
        )
    }
    return (
        <CodeSnippet language={Language.XML}>
            {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.API_KEY</key>\n\t<string>' +
                currentTeam?.api_token +
                '</string>\n\t<key>com.posthog.posthog.POSTHOG_HOST</key>\n\t<string>' +
                url +
                '</string>\n\t<key>com.posthog.posthog.CAPTURE_APPLICATION_LIFECYCLE_EVENTS</key>\n\t<true/>\n\t[...]\n</dict>'}
        </CodeSnippet>
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

  <body>
    ...
  </body>
</html>`}
        </CodeSnippet>
    )
}

export function SDKInstallFlutterInstructions(props: FlutterSetupProps): JSX.Element {
    return (
        <>
            {props.includeReplay ? (
                <LemonBanner type="info">
                    🚧 NOTE: <Link to="https://posthog.com/docs/session-replay/mobile">Mobile recording</Link> is
                    currently in beta. We are keen to gather as much feedback as possible so if you try this out please
                    let us know. You can send feedback via the{' '}
                    <Link to="https://us.posthog.com/#panel=support%3Afeedback%3Asession_replay%3Alow">
                        in-app support panel
                    </Link>{' '}
                    or one of our other <Link to="https://posthog.com/docs/support-options">support options</Link>.
                </LemonBanner>
            ) : null}
            <h3>Install</h3>
            <FlutterInstallSnippet />
            <h3>Android Setup</h3>
            <p className="prompt-text">Add these values in AndroidManifest.xml</p>
            <FlutterAndroidSetupSnippet {...props} />
            <h3>iOS/macOS Setup</h3>
            <p className="prompt-text">Add these values in Info.plist</p>
            <FlutterIOSSetupSnippet {...props} />
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
