import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const DjangoInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()

    const PythonEventCapture = snippets?.PythonEventCapture

    return (
        <Steps>
            <Step title="Install the package" badge="required">
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
            </Step>

            <Step title="Configure PostHog" badge="required">
                <Markdown>
                    Set the PostHog API key and host in your `AppConfig` in `apps.py` so that it's available everywhere:
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
                    Next, if you haven't done so already, make sure you add your `AppConfig` to your `settings.py` under
                    `INSTALLED_APPS`:
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
            </Step>

            <Step title="Send events">{PythonEventCapture && <PythonEventCapture />}</Step>
        </Steps>
    )
}
