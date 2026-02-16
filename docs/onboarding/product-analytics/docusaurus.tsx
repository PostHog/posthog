import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getDocusaurusSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Install the plugin',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Configure the plugin',
            badge: 'required',
            content: (
                <>
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
                            See the [Docusaurus integration docs](https://posthog.com/docs/libraries/docusaurus) for
                            more configuration options.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'View events',
            content: (
                <Markdown>
                    Start your Docusaurus site and visit a few pages. PostHog will automatically capture pageviews and
                    other events.
                </Markdown>
            ),
        },
    ]
}

export const DocusaurusInstallation = createInstallation(getDocusaurusSteps)
