import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getFlutterSteps as getFlutterStepsPA } from '../product-analytics/flutter'
import { StepDefinition } from '../steps'

export const getFlutterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getFlutterStepsPA(ctx)

    const sendLogStep: StepDefinition = {
        title: 'Send a log',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    Capture a structured log record with `Posthog().logger`. Requires `posthog_flutter` 5.27.0 or later.
                    Records are batched and shipped to PostHog's logs product.
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'dart',
                            file: 'Dart',
                            code: dedent`
                                import 'package:posthog_flutter/posthog_flutter.dart';

                                Posthog().logger.info('checkout completed', {
                                    'order_id': 'ord_789',
                                });
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Logs appear in PostHog within a few seconds. Use the [Logs page](https://app.posthog.com/logs) to search and filter
                        by service name, severity, or any attribute you attach.
                    `}
                </Markdown>
            </>
        ),
    }

    return [...installSteps, sendLogStep]
}

export const FlutterInstallation = createInstallation(getFlutterSteps)
