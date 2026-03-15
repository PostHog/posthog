import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const JSInitSnippet = ({ defaultsDate }: { defaultsDate: string }): JSX.Element => {
    const { CodeBlock, dedent } = useMDXComponents()

    return (
        <CodeBlock
            blocks={[
                {
                    language: 'javascript',
                    file: 'JavaScript',
                    code: dedent`
                        import posthog from 'posthog-js'

                        posthog.init('<ph_project_token>', {
                            api_host: '<ph_client_api_host>',
                            defaults: '${defaultsDate}'
                        })
                    `,
                },
            ]}
        />
    )
}
