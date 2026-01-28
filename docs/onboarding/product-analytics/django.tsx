import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getDjangoSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx

    const PythonEventCapture = snippets?.PythonEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog Python library using pip:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    pip install posthog
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Set the PostHog API key and host in your `AppConfig` in `apps.py` so that it's available
                        everywhere:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'your_app/apps.py',
                                code: dedent`
                                    from django.apps import AppConfig
                                    import posthog

                                    class YourAppConfig(AppConfig):
                                        name = "your_app_name"

                                        def ready(self):
                                            posthog.api_key = '<ph_project_api_key>'
                                            posthog.host = '<ph_client_api_host>'
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Next, if you haven't done so already, make sure you add your `AppConfig` to your `settings.py`
                        under `INSTALLED_APPS`:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'settings.py',
                                code: dedent`
                                    INSTALLED_APPS = [
                                        # other apps
                                        'your_app_name.apps.YourAppConfig',  # Add your app config
                                    ]
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            content: <>{PythonEventCapture && <PythonEventCapture />}</>,
        },
    ]
}

export const DjangoInstallation = createInstallation(getDjangoSteps)
