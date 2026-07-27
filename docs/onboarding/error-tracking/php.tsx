import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getPHPSteps as getPHPStepsPA } from '../product-analytics/php'
import { StepDefinition } from '../steps'

export const getPHPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getPHPStepsPA(ctx)

    const automaticCaptureStep: StepDefinition = {
        title: 'Configure automatic error tracking',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Enable PHP error tracking when initializing PostHog to capture exceptions, PHP errors, and fatal shutdown errors.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'php',
                            file: 'PHP',
                            code: dedent`
                                PostHog\\PostHog::init('<ph_project_token>', [
                                    'host' => '<ph_client_api_host>',
                                    'error_tracking' => [
                                        'enabled' => true,
                                        'capture_errors' => true,
                                        'excluded_exceptions' => [
                                            \\InvalidArgumentException::class,
                                        ],
                                        'context_provider' => static function (array $payload): array {
                                            return [
                                                'distinctId' => $_SESSION['user_id'] ?? null,
                                                'properties' => [
                                                    '$current_url' => $_SERVER['REQUEST_URI'] ?? null,
                                                ],
                                            ];
                                        },
                                    ],
                                ]);
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        For handled exceptions that should still appear in Error tracking, call \`captureException\`.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'php',
                            file: 'PHP',
                            code: dedent`
                                try {
                                    throw new Exception('Something went wrong');
                                } catch (Exception $exception) {
                                    PostHog\\PostHog::captureException($exception, 'user_distinct_id', [
                                        '$current_url' => 'https://example.com/checkout',
                                    ]);
                                }
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Confirm exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, automaticCaptureStep, manualCaptureStep, verifyStep]
}

export const PHPInstallation = createInstallation(getPHPSteps)
