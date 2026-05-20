import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Tab, dedent, snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture
    const JSHtmlSnippet = snippets?.JSHtmlSnippet
    const JSInitSnippet = snippets?.JSInitSnippet

    return [
        {
            title: 'Choose an installation method',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        You can either add the JavaScript snippet directly to your HTML or install the JavaScript SDK
                        via your package manager.
                    </Markdown>

                    <Tab.Group tabs={['HTML snippet', 'JavaScript SDK']}>
                        <Tab.List>
                            <Tab>HTML snippet</Tab>
                            <Tab>JavaScript SDK</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    Add this snippet to your website within the `&lt;head&gt;` tag. This can also be
                                    used in services like Google Tag Manager:
                                </Markdown>
                                {JSHtmlSnippet && <JSHtmlSnippet />}
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        Install the PostHog JavaScript library using your package manager.
                                        Then, import and initialize the PostHog library with your project token and host:
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'bash',
                                            file: 'npm',
                                            code: dedent`
                                                npm install posthog-js
                                            `,
                                        },
                                        {
                                            language: 'bash',
                                            file: 'yarn',
                                            code: dedent`
                                                yarn add posthog-js
                                            `,
                                        },
                                        {
                                            language: 'bash',
                                            file: 'pnpm',
                                            code: dedent`
                                                pnpm add posthog-js
                                            `,
                                        },
                                    ]}
                                />
                                {JSInitSnippet && <JSInitSnippet />}
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Once installed, PostHog will automatically start capturing events. You can also manually send
                        events to test your integration:
                    </Markdown>
                    {JSEventCapture && <JSEventCapture />}
                </>
            ),
        },
    ]
}

export const WebInstallation = createInstallation(getWebSteps)
