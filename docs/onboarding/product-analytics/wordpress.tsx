import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getWordpressSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Install via plugin (recommended)',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install a header/footer script plugin like
                        [WPCode](https://wordpress.org/plugins/insert-headers-and-footers/) or similar. Go to the plugin
                        settings and add a new header script with the following code:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'HTML',
                                code: dedent`
                                <script>
                                    ${snippetFunctions(DEFAULT_SNIPPET_METHODS)}
                                    posthog.init('<ph_project_token>', {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '${SDK_DEFAULTS_DATE}'
                                    })
                                </script>
                            `,
                            },
                        ]}
                    />
                    <Markdown>Save and activate the script.</Markdown>
                </>
            ),
        },
        {
            title: 'Alternative: Edit theme directly',
            content: (
                <>
                    <Markdown>
                        {`Add the same code snippet to your theme's \`header.php\` file, just before the closing \`</head>\` tag. Note: this may be overwritten when updating themes.`}
                    </Markdown>
                    <CalloutBox type="fyi" title="More details">
                        <Markdown>
                            See the [WordPress integration docs](https://posthog.com/docs/libraries/wordpress) for more
                            details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
    ]
}

export const WordpressInstallation = createInstallation(getWordpressSteps)
