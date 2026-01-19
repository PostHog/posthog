import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const DocusaurusInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the plugin" badge="required">
                <Markdown>
                    Docusaurus is a popular static site generator for documentation. You can add PostHog using the
                    official plugin:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Terminal',
                            code: dedent`
                                npm install --save posthog-docusaurus
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Configure the plugin" badge="required">
                <Markdown>Add the plugin to your `docusaurus.config.js`:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'docusaurus.config.js',
                            code: dedent`
                                module.exports = {
                                  plugins: [
                                    [
                                      'posthog-docusaurus',
                                      {
                                        apiKey: '<ph_project_api_key>',
                                        appUrl: '<ph_client_api_host>',
                                        enableInDevelopment: false,
                                      },
                                    ],
                                  ],
                                }
                            `,
                        },
                    ]}
                />
                <CalloutBox type="fyi" title="More options">
                    <Markdown>
                        See the [Docusaurus integration docs](https://posthog.com/docs/libraries/docusaurus) for more
                        configuration options.
                    </Markdown>
                </CalloutBox>
            </Step>

            <Step title="View events">
                <Markdown>
                    Start your Docusaurus site and visit a few pages. PostHog will automatically capture pageviews and
                    other events.
                </Markdown>
            </Step>
        </Steps>
    )
}
