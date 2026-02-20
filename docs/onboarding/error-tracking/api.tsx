import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

const propertyColumnStyle = { minWidth: '200px', maxWidth: '250px' }

export const getAPISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Learn the API schema',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Error tracking enables you to track, investigate, and resolve exceptions your customers face.
                    
                            If a platform you use is not supported by error tracking, we recommend that you reach out to us or contribute to our open-source SDKs before attempting to manually send exceptions.
                    
                            If you'd rather roll your own exception capturing (or if you're using a platform we don't have an SDK for), you can use the [capture API](/docs/api/capture.md) or \`capture\` method to capture an \`$exception\` event with the following properties:
                        `}
                    </Markdown>
                    <div className="LemonMarkdown">
                        <table className="my-4">
                            <thead>
                                <tr>
                                    <th style={propertyColumnStyle}>Property</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td style={propertyColumnStyle}>
                                        <code>$exception_list</code>
                                    </td>
                                    <td>
                                        A list of exception objects with detailed information about each error. Each exception can include a type, value, mechanism, module, and a stacktrace with frames and type. You can find the expected schema as types for both exception and stack frames in our Rust repo
                                    </td>
                                </tr>
                                <tr>
                                    <td style={propertyColumnStyle}>
                                        <code>$exception_fingerprint</code>
                                    </td>
                                    <td>
                                        (Optional) The identifier used to group issues. If not set, a unique hash based on the exception pattern will be generated during ingestion
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </>
            ),
        },
        {
            title: 'Make a request',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Example exception API capture:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                  curl -X POST "https://us.i.posthog.com/i/v0/e/" \\
                                       -H "Content-Type: application/json" \\
                                       -d '{
                                          "api_key": "<ph_project_api_key>",
                                          "event": "$exception",
                                          "properties": {
                                              "distinct_id": "distinct_id_of_your_user",
                                              "$exception_list": [{
                                                  "type": "RangeError",
                                                  "value": "Maximum call stack size exceeded",
                                                  "mechanism": {
                                                      "handled": true,
                                                      "synthetic": false
                                                  },
                                                  "stacktrace": {
                                                      "type": "raw",
                                                      "frames": [
                                                          {
                                                              "platform": "custom", // (Required) Must be custom
                                                              "lang": "javascript", // (Required) Your programming language
                                                              "function": "Array.forEach", // (Required)
                                                              "filename": "../loop.js", // (Optional)
                                                              "lineno": 1, // (Optional)
                                                              "colno": 2, // (Optional)
                                                              "module": "iteration", // (Optional)
                                                              "resolved": true, // (Optional)
                                                              "in_app": false, // (Optional)
                                                          },
                                                          /* Additional frames omitted for brevity */
                                                      ]
                                                  }
                                              }],
                                              "$exception_fingerprint": "209842d96784e19321e3a36b068d53fff7a01ebcb1da9e98df35c4c49db0b4f3b62aea7ee25a714470e61f8d36b4716f227f241c153477e5fa9adfda64ce9f71"
                                          },
                                      }'
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const APIInstallation = createInstallation(getAPISteps)