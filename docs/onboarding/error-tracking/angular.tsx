import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAngularSteps as getAngularStepsPA } from '../product-analytics/angular'
import { StepDefinition } from '../steps'

export const getAngularSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getAngularStepsPA(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Setting up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Exception autocapture can be enabled during initialization of the PostHog client to automatically capture any exception thrown by your Angular application.

                        This requires overriding Angular's default \`ErrorHandler\` provider:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'src/app/posthog-error-handler.ts',
                            code: dedent`
                              import { ErrorHandler, Injectable, Provider } from '@angular/core';
                              import { HttpErrorResponse } from '@angular/common/http';
                              import posthog from 'posthog-js';
                              
                              @Injectable({ providedIn: 'root' })
                              class PostHogErrorHandler implements ErrorHandler {
                                public constructor() {}
                                public handleError(error: unknown): void {
                                  const extractedError = this._extractError(error) || 'Unknown error';
                                  runOutsideAngular(() => posthog.captureException(extractedError));
                                }
                                protected _extractError(errorCandidate: unknown): unknown {
                                  const error = tryToUnwrapZonejsError(errorCandidate);
                                  if (error instanceof HttpErrorResponse) {
                                    return extractHttpModuleError(error);
                                  }
                                  if (typeof error === 'string' || isErrorOrErrorLikeObject(error)) {
                                    return error;
                                  }
                                  return null;
                                }
                              }
                              
                              function tryToUnwrapZonejsError(error: unknown): unknown | Error {
                                return error && (error as { ngOriginalError: Error }).ngOriginalError
                                  ? (error as { ngOriginalError: Error }).ngOriginalError
                                  : error;
                              }
                              
                              function extractHttpModuleError(error: HttpErrorResponse): string | Error {
                                if (isErrorOrErrorLikeObject(error.error)) {
                                  return error.error;
                                }
                                if (
                                  typeof ErrorEvent !== 'undefined' &&
                                  error.error instanceof ErrorEvent &&
                                  error.error.message
                                ) {
                                  return error.error.message;
                                }
                                if (typeof error.error === 'string') {
                                  return \`Server returned code \${error.status} with body "\${error.error}"\`;
                                }
                                return error.message;
                              }
                              
                              function isErrorOrErrorLikeObject(value: unknown): value is Error {
                                if (value instanceof Error) {
                                  return true;
                                }
                                if (value === null || typeof value !== 'object' || Array.isArray(value)) {
                                  return false;
                                }
                                return 'name' in value && 'message' in value && 'stack' in value;
                              }
                              
                              declare const Zone: any;
                              // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
                              const isNgZoneEnabled = typeof Zone !== 'undefined' && Zone.root?.run;
                              export function runOutsideAngular<T>(callback: () => T): T {
                                // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
                                return isNgZoneEnabled ? Zone.root.run(callback) : callback();
                              }
                              
                              export function providePostHogErrorHandler(): Provider {
                                return {
                                  provide: ErrorHandler,
                                  useValue: new PostHogErrorHandler(),
                                };
                              }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Then, in your \`src/app/app.config.ts\`, import the \`providePostHogErrorHandler\` function and add it to the providers array:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'src/app/app.config.ts',
                            code: dedent`
                              // src/app/app.config.ts
                              import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
                              import { provideRouter } from '@angular/router';

                              import { routes } from './app.routes';
                              import { providePostHogErrorHandler } from './posthog-error-handler'; // +
                              export const appConfig: ApplicationConfig = {
                                providers: [
                                  ...
                                  providePostHogErrorHandler(), // +
                                ],
                              };
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
                        If there are more errors you'd like to capture, you can manually call the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'TypeScript',
                            code: dedent`
                              posthog.captureException(e, additionalProperties)
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

    return [
        ...installSteps,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
    ]
}

export const AngularInstallation = createInstallation(getAngularSteps)
