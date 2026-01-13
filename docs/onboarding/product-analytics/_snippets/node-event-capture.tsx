import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const NodeEventCapture =function NodeEventCapture(): JSX.Element {
    const { Markdown, CodeBlock, CalloutBox, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>Capture custom events by calling the `capture` method:</Markdown>
            <CodeBlock
                blocks={[
                    {
                        language: 'javascript',
                        file: 'Node.js',
                        code: dedent`
                            client.capture({
                                distinctId: 'user_123',
                                event: 'user_signed_up',
                                properties: {
                                    plan: 'pro',
                                    source: 'organic'
                                }
                            })

                            // Send queued events immediately. Use for example in a serverless environment
                            // where the program may terminate before everything is sent.
                            // Use \`client.flush()\` instead if you still need to send more events or fetch feature flags.
                            client.shutdown()
                        `,
                    },
                ]}
            />
            <CalloutBox type="fyi" title="Serverless environments">
                <Markdown>
                    In serverless environments like AWS Lambda or Vercel Edge Functions, call `client.shutdown()` before
                    the function returns to ensure all events are sent.
                </Markdown>
            </CalloutBox>
        </>
    )
}
