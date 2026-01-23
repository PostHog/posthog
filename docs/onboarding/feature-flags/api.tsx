import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getAPISteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    options?: StepModifier
): StepDefinition[] => {
    const steps: StepDefinition[] = [
        {
            title: 'Evaluate the feature flag value using flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            \`flags\` is the endpoint used to determine if a given flag is enabled for a certain user or not.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Basic request (flags only)',
                                code: dedent`
                                    curl -v -L --header "Content-Type: application/json" -d '{
                                        "api_key": "<ph_project_api_key>",
                                        "distinct_id": "distinct_id_of_your_user",
                                        "groups" : {
                                            "group_type": "group_id"
                                        }
                                    }' "<ph_client_api_host>/flags?v=2"
                                `,
                            },
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import requests
                                    import json

                                    url = "<ph_client_api_host>/flags?v=2"
                                    headers = {
                                        "Content-Type": "application/json"
                                    }
                                    payload = {
                                        "api_key": "<ph_project_api_key>",
                                        "distinct_id": "user distinct id",
                                        "groups": {
                                            "group_type": "group_id"
                                        }
                                    }
                                    response = requests.post(url, headers=headers, data=json.dumps(payload))
                                    print(response.json())
                                `,
                            },
                            {
                                language: 'javascript',
                                file: 'Node.js',
                                code: dedent`
                                    const response = await fetch("<ph_client_api_host>/flags?v=2", {
                                        method: "POST",
                                        headers: {
                                            "Content-Type": "application/json",
                                        },
                                        body: JSON.stringify({
                                            api_key: "<ph_project_api_key>",
                                            distinct_id: "user distinct id",
                                            groups: {
                                                group_type: "group_id",
                                            },
                                        }),
                                    });
                                    const data = await response.json();
                                    console.log(data);
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        {dedent`
                            **Note:** The \`groups\` key is only required for group-based feature flags. If you use it, replace \`group_type\` and \`group_id\` with the values for your group such as \`company: "Twitter"\`.
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Include feature flag information when capturing events',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            If you want to use your feature flag to breakdown or filter events in your insights, you'll need to include feature flag information in those events. This ensures that the feature flag value is attributed correctly to the event.

                            **Note:** This step is only required for events captured using our server-side SDKs or API.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    curl -v -L --header "Content-Type: application/json" -d '{
                                        "api_key": "<ph_project_api_key>",
                                        "event": "your_event_name",
                                        "distinct_id": "distinct_id_of_your_user",
                                        "properties": {
                                            "$feature/feature-flag-key": "variant-key"
                                        }
                                    }' <ph_client_api_host>/i/v0/e/
                                `,
                            },
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import requests
                                    import json

                                    url = "<ph_client_api_host>/i/v0/e/"
                                    headers = {
                                        "Content-Type": "application/json"
                                    }
                                    payload = {
                                        "api_key": "<ph_project_api_key>",
                                        "event": "your_event_name",
                                        "distinct_id": "distinct_id_of_your_user",
                                        "properties": {
                                            "$feature/feature-flag-key": "variant-key"
                                        }
                                    }
                                    response = requests.post(url, headers=headers, data=json.dumps(payload))
                                    print(response)
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send a $feature_flag_called event',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            To track usage of your feature flag and view related analytics in PostHog, submit the \`$feature_flag_called\` event whenever you check a feature flag value in your code.

                            You need to include two properties with this event:
                            1. \`$feature_flag_response\`: This is the name of the variant the user has been assigned to e.g., "control" or "test"
                            2. \`$feature_flag\`: This is the key of the feature flag in your experiment.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    curl -v -L --header "Content-Type: application/json" -d '{
                                        "api_key": "<ph_project_api_key>",
                                        "event": "$feature_flag_called",
                                        "distinct_id": "distinct_id_of_your_user",
                                        "properties": {
                                            "$feature_flag": "feature-flag-key",
                                            "$feature_flag_response": "variant-name"
                                        }
                                    }' <ph_client_api_host>/i/v0/e/
                                `,
                            },
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import requests
                                    import json

                                    url = "<ph_client_api_host>/i/v0/e/"
                                    headers = {
                                        "Content-Type": "application/json"
                                    }
                                    payload = {
                                        "api_key": "<ph_project_api_key>",
                                        "event": "$feature_flag_called",
                                        "distinct_id": "distinct_id_of_your_user",
                                        "properties": {
                                            "$feature_flag": "feature-flag-key",
                                            "$feature_flag_response": "variant-name"
                                        }
                                    }
                                    response = requests.post(url, headers=headers, data=json.dumps(payload))
                                    print(response)
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Running experiments',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an experiment by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]
    return options?.modifySteps ? options.modifySteps(steps) : steps
}

export const APIInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    const steps = getAPISteps(CodeBlock, Markdown, dedent, { modifySteps })

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}
