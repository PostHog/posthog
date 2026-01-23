import { getFlutterSteps as getFlutterStepsPA } from '../product-analytics/flutter'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getFlutterSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    options?: StepModifier
): StepDefinition[] => {

    const installationSteps = getFlutterStepsPA(CodeBlock, Markdown, dedent)

    // Add survey steps here if needed
    const surveySteps: StepDefinition[] = [
        {
            title: 'Install the PosthogObserver',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        For surveys to be shown, you need to add the PosthogObserver to your app. The observer allows PostHog to determine the appropriate context for displaying surveys.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'dart',
                                file: 'Dart',
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
                </>
            )
        }
    ]

    const allSteps = [...installationSteps, ...surveySteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const FlutterInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getFlutterSteps(CodeBlock, Markdown, dedent, { modifySteps })

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
