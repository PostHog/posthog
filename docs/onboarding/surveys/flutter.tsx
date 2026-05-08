import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFlutterSteps } from '../product-analytics/flutter'
import { StepDefinition } from '../steps'

function getSurveysFlutterSteps(ctx: OnboardingComponentsContext): StepDefinition[] {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const SurveysFinalSteps = snippets?.SurveysFinalSteps

    const installationSteps = getFlutterSteps(ctx)

    const surveysSteps: StepDefinition[] = [
        {
            title: 'Install PosthogObserver',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        For surveys to be shown, you need to add the PosthogObserver to your app. The observer allows
                        PostHog to determine the appropriate context for displaying surveys.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'dart',
                                file: 'main.dart',
                                code: dedent`
                                    import 'package:flutter/material.dart';

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
                    <Markdown>
                        {dedent`
                            If you're using go_router, check [this page](https://posthog.com/docs/surveys/installation/flutter) to learn how to set up the PosthogObserver.
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configuration',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        **Important:** For Flutter Web, surveys are powered by the JavaScript Web SDK, so any
                        Flutter-specific survey configuration will be ignored. Please refer to the Web installation
                        guide for proper setup.
                    </Markdown>
                    <Markdown>
                        Surveys are enabled by default. If you want to disable surveys, you can do so when setting up
                        your SDK instance:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'dart',
                                file: 'main.dart',
                                code: dedent`
                                    final config = PostHogConfig('<ph_project_token>');

                                    config.surveys = false; // Disable surveys
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]

    return [
        ...installationSteps,
        ...surveysSteps,
        {
            title: 'Next steps',
            badge: 'recommended',
            content: <>{SurveysFinalSteps && <SurveysFinalSteps />}</>,
        },
    ]
}

export const SurveysFlutterInstallation = createInstallation(getSurveysFlutterSteps)
