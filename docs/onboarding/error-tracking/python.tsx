import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getPythonSteps as getPythonStepsPA } from '../product-analytics/python'
import { StepDefinition } from '../steps'

export const getPythonSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Tab, dedent } = ctx

    const installSteps = getPythonStepsPA(ctx)

    const verifyInitStep: StepDefinition = {
        title: 'Verify PostHog is initialized',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Before proceeding, enable debug and call \`posthog.capture('test_event')\` to make sure you can capture events.
                `}
            </Markdown>
        ),
    }

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Setting up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Exception autocapture can be enabled during initialization of the PostHog client to automatically capture any unhandled exceptions thrown by your Python application. It works by setting Python's built-in exception hooks, such as \`sys.excepthook\` and \`threading.excepthook\`.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                from posthog import Posthog
                                posthog = Posthog("<ph_project_api_key>", enable_exception_autocapture=True, ...)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        We recommend setting up and using [contexts](/docs/libraries/python#contexts) so that exceptions automatically include distinct IDs, session IDs, and other properties you can set up with tags.

                        You can also enable [code variables capture](/docs/error-tracking/code-variables/python) to automatically capture the state of local variables when exceptions occur, giving you a debugger-like view of your application.
                    `}
                </Markdown>
            </>
        ),
    }

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capturing exceptions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        For exceptions handled by your application that you would still like sent to PostHog, you can manually call the capture method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                posthog.capture_exception(e, distinct_id="user_distinct_id", properties=additional_properties)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        You can find a full example of all of this in our [Python (and Flask) error tracking tutorial](/tutorials/python-error-tracking).
                    `}
                </Markdown>
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

    const frameworkStep: StepDefinition = {
        title: 'Framework-specific exception capture',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Python frameworks often have built-in error handlers. This means PostHog's default exception autocapture won't work and we need to manually capture errors instead. The exact process depends on the framework:
                    `}
                </Markdown>
                <Tab.Group tabs={['Django', 'Flask', 'FastAPI']}>
                    <Tab.List>
                        <Tab>Django</Tab>
                        <Tab>Flask</Tab>
                        <Tab>FastAPI</Tab>
                    </Tab.List>
                    <Tab.Panels>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    The Python SDK provides a Django middleware that automatically wraps all requests with a [context](/docs/libraries/python#contexts). Add the middleware to your Django settings:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'Python',
                                        code: dedent`
                                            MIDDLEWARE = [
                                                # ... other middleware
                                                'posthog.integrations.django.PosthogContextMiddleware',
                                                # ... other middleware
                                            ]
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    By default, the middleware captures exceptions and sends them to PostHog. Disable with \`POSTHOG_MW_CAPTURE_EXCEPTIONS = False\`. Use \`POSTHOG_MW_EXTRA_TAGS\`, \`POSTHOG_MW_REQUEST_FILTER\`, and \`POSTHOG_MW_TAG_MAP\` to customize. See the [Django integration docs](/docs/libraries/django) for full configuration.
                                `}
                            </Markdown>
                        </Tab.Panel>
                        <Tab.Panel>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'Python',
                                        code: dedent`
                                            from flask import Flask, jsonify
                                            from posthog import Posthog
                                            posthog = Posthog('<ph_project_api_key>', host='https://us.i.posthog.com')
                                            @app.errorhandler(Exception)
                                            def handle_exception(e):
                                                event_id = posthog.capture_exception(e)
                                                response = jsonify({'message': str(e), 'error_id': event_id})
                                                response.status_code = 500
                                                return response
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                        <Tab.Panel>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'Python',
                                        code: dedent`
                                            from fastapi.responses import JSONResponse
                                            from posthog import Posthog
                                            posthog = Posthog('<ph_project_api_key>', host='https://us.i.posthog.com')
                                            @app.exception_handler(Exception)
                                            async def http_exception_handler(request, exc):
                                                posthog.capture_exception(exc)
                                                return JSONResponse(status_code=500, content={'message': str(exc)})
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
            </>
        ),
    }

    return [
        ...installSteps,
        verifyInitStep,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
        frameworkStep,
    ]
}

export const PythonInstallation = createInstallation(getPythonSteps)
