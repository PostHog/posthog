import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getFlutterSteps as getFlutterStepsPA } from '../product-analytics/flutter'
import { StepDefinition } from '../steps'

export const getFlutterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getFlutterStepsPA(ctx)

    // Replace the "Send events" step with web analytics specific content
    const webAnalyticsSteps = paSteps.map((step) => {
        if (step.title === 'Send events') {
            return {
                title: 'Track screen views',
                badge: 'recommended' as const,
                content: (
                    <>
                        {MobileFinalSteps && <MobileFinalSteps />}
                        <Markdown>
                            To automatically capture screen views, you can use the `PostHogObserver` with your
                            navigation:
                        </Markdown>
                        <CodeBlock
                            blocks={[
                                {
                                    language: 'dart',
                                    file: 'Dart',
                                    code: dedent`
                                        import 'package:posthog_flutter/posthog_flutter.dart';

                                        MaterialApp(
                                            navigatorObservers: [
                                                PosthogObserver(),
                                            ],
                                            // rest of your app
                                        )
                                    `,
                                },
                            ]}
                        />
                    </>
                ),
            }
        }
        return step
    })

    return webAnalyticsSteps
}

export const FlutterInstallation = createInstallation(getFlutterSteps)
