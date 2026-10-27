import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

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
                                posthog = Posthog("<ph_project_token>", enable_exception_autocapture=True, ...)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        We recommend setting up and using [contexts](https://posthog.com/docs/libraries/python#contexts) so that exceptions automatically include distinct IDs, session IDs, and other properties you can set up with tags.

                        You can also enable [code variables capture](https://posthog.com/docs/error-tracking/code-variables/python) to automatically capture the state of local variables when exceptions occur, giving you a debugger-like view of your application.
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
                        You can find a full example of all of this in our [Python (and Flask) error tracking tutorial](https://posthog.com/tutorials/python-error-tracking).
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

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/events)
                `}
            </Markdown>
        ),
    }

    const frameworkStep: StepDefinition = {
        title: 'Framework-specific exception capture',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Web frameworks catch exceptions raised in your routes and turn them into error responses, so these exceptions never reach the hooks that exception autocapture uses. The Python SDK includes integrations for Django, Flask, and ASGI frameworks such as FastAPI. They capture these exceptions and add request properties to every event captured during a request. The Flask, ASGI, and Django REST Framework integrations require version \`7.69.0\` or later of the Python SDK.
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
                                    Add the Django middleware to your settings. It wraps each request in a [context](https://posthog.com/docs/libraries/python#contexts) and captures exceptions raised by your views.

                                    The middleware sends exceptions through the global \`posthog\` client. When you create your own client with \`Posthog(...)\`, set it as \`POSTHOG_MW_CLIENT\`. Otherwise the middleware sends exceptions to the unconfigured global client, and they don't reach PostHog:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'settings.py',
                                        code: dedent`
                                            from posthog import Posthog

                                            POSTHOG_MW_CLIENT = Posthog(
                                                '<ph_project_token>',
                                                host='<ph_client_api_host>',
                                                enable_exception_autocapture=True,
                                            )

                                            MIDDLEWARE = [
                                                # ... other middleware
                                                'posthog.integrations.django.PosthogContextMiddleware',
                                            ]
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    If you configure the global client instead, with \`posthog.api_key\` and \`posthog.host\`, leave \`POSTHOG_MW_CLIENT\` unset.

                                    Django REST Framework converts exceptions into error responses before the middleware sees them. If you use it, also add the DRF exception handler:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'settings.py',
                                        code: dedent`
                                            REST_FRAMEWORK = {
                                                # ... other DRF settings
                                                'EXCEPTION_HANDLER': 'posthog.integrations.drf.exception_handler',
                                            }
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    Set \`POSTHOG_MW_CAPTURE_EXCEPTIONS = False\` to keep the request context without exception capture. See the [Django integration docs](https://posthog.com/docs/libraries/django#exception-capture) for all settings.
                                `}
                            </Markdown>
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    Register the Flask integration with your app and your client. It captures unhandled exceptions raised by your routes:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'Python',
                                        code: dedent`
                                            from flask import Flask
                                            from posthog import Posthog
                                            from posthog.integrations.flask import PosthogFlaskIntegration

                                            app = Flask(__name__)
                                            posthog = Posthog(
                                                '<ph_project_token>',
                                                host='<ph_client_api_host>',
                                                enable_exception_autocapture=True,
                                            )

                                            PosthogFlaskIntegration(app, client=posthog)
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    The integration doesn't capture expected HTTP exceptions, such as \`404 Not Found\`, or exceptions that your own error handlers consume. To report an exception that you handle, call \`posthog.capture_exception(e)\` in the handler. See the [Flask integration docs](https://posthog.com/docs/libraries/flask#error-tracking).
                                `}
                            </Markdown>
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    Add the ASGI middleware to your app. It captures exceptions that escape your routes. It works the same way for Starlette, Litestar, and other ASGI frameworks:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'python',
                                        file: 'Python',
                                        code: dedent`
                                            from fastapi import FastAPI
                                            from posthog import Posthog
                                            from posthog.integrations.asgi import PosthogASGIMiddleware

                                            posthog = Posthog(
                                                '<ph_project_token>',
                                                host='<ph_client_api_host>',
                                                enable_exception_autocapture=True,
                                            )

                                            app = FastAPI()
                                            app.add_middleware(PosthogASGIMiddleware, client=posthog)
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    The middleware still captures an exception that an \`@app.exception_handler(Exception)\` catch-all handles. A handler for a specific exception class, such as \`@app.exception_handler(ValueError)\`, turns that exception into a response before the middleware sees it. To report those exceptions, call \`posthog.capture_exception(exc)\` in the handler. See the [ASGI middleware docs](https://posthog.com/docs/libraries/python#asgi-request-middleware).
                                `}
                            </Markdown>
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
            </>
        ),
    }

    return [...installSteps, verifyInitStep, exceptionAutocaptureStep, manualCaptureStep, verifyStep, frameworkStep]
}

export const PythonInstallation = createInstallation(getPythonSteps)
