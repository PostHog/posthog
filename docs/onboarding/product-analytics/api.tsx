import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const APIInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Send events via the API" badge="required">
                <Markdown>
                    You can send events directly to the PostHog API from any programming language or platform that can
                    make HTTP requests:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'http',
                            file: 'HTTP',
                            code: dedent`
                                POST <ph_client_api_host>/capture/
                                Content-Type: application/json

                                {
                                    "api_key": "<ph_project_api_key>",
                                    "event": "[event name]",
                                    "properties": {
                                        "distinct_id": "[your users' distinct id]",
                                        "key1": "value1",
                                        "key2": "value2"
                                    },
                                    "timestamp": "[optional timestamp in ISO 8601 format]"
                                }
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Person profiles" badge="optional">
                <Markdown>
                    By default, events are sent with person profile processing enabled. To disable this for specific
                    events, add the following property:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'json',
                            file: 'JSON',
                            code: dedent`
                                {
                                    "api_key": "<ph_project_api_key>",
                                    "event": "page_viewed",
                                    "properties": {
                                        "distinct_id": "user_123",
                                        "$process_person_profile": false
                                    }
                                }
                            `,
                        },
                    ]}
                />
                <CalloutBox type="fyi" title="Learn more">
                    <Markdown>
                        Read more about [person profiles](https://posthog.com/docs/data/persons) in our documentation.
                    </Markdown>
                </CalloutBox>
            </Step>
        </Steps>
    )
}
