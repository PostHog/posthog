import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

const ADD_DESTINATION_SCREENSHOT = '/images/docs/ai-observability/claude-platform-add-destination.png'
const MANAGED_AGENTS_TRACE_SCREENSHOT = '/images/docs/ai-observability/claude-platform-managed-agents-trace.png'
const ANTHROPIC_OTEL_GUIDE = 'https://platform.claude.com/docs/en/manage-claude/opentelemetry'

const getProjectTokenStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown, dedent, snippets } = ctx
    const ProjectToken = snippets?.ProjectToken

    return {
        title: 'Copy your project token',
        badge: 'required',
        content: (
            <>
                {ProjectToken ? (
                    <ProjectToken />
                ) : (
                    <Markdown>
                        {dedent`
                            Copy your project token from your [project settings](https://app.posthog.com/settings/project#variables). It starts with \`phc_\`.
                        `}
                    </Markdown>
                )}
                <Markdown>A personal API key (`phx_...`) won't work here.</Markdown>
            </>
        ),
    }
}

const getAddDestinationStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown, ProductScreenshot, dedent } = ctx

    return {
        title: 'Add PostHog in the Claude Console',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        In the Claude Console, open the [OpenTelemetry settings](https://platform.claude.com/settings/telemetry-destinations) of your organization and click **Add destination**. You need an admin role.

                        1. **Provider:** PostHog.
                        2. **Region:** US if you log in at \`us.posthog.com\`, EU if you log in at \`eu.posthog.com\`.
                        3. **Project token:** paste your \`phc_\` token.
                        4. **Content mode:** pick **Full content** to see every prompt and response in PostHog. **Metadata only** sends tokens, costs, and timing without the messages.
                        5. **Set as organization default:** select it so every workspace sends its traces to PostHog.
                    `}
                </Markdown>

                <ProductScreenshot
                    imageLight={ADD_DESTINATION_SCREENSHOT}
                    imageDark={ADD_DESTINATION_SCREENSHOT}
                    alt="The Add destination form in the Claude Console with PostHog selected as the provider"
                    classes="rounded"
                />

                <Markdown>
                    {dedent`
                        Click **Add destination**. That's the whole setup.

                        Anthropic's [OpenTelemetry guide](${ANTHROPIC_OTEL_GUIDE}) covers workspace destinations, delivery health, and every span and attribute. New to OpenTelemetry? The [OpenTelemetry docs](https://opentelemetry.io/docs/concepts/signals/traces/) explain traces and spans.
                    `}
                </Markdown>
            </>
        ),
    }
}

const getTroubleshootingStep = (ctx: OnboardingComponentsContext, items: string): StepDefinition => {
    const { Markdown } = ctx

    return {
        title: 'Troubleshooting',
        badge: 'optional',
        content: (
            <Markdown>
                {`${items}\n\nFor other questions, see [AI Observability troubleshooting](/docs/ai-observability/troubleshooting).`}
            </Markdown>
        ),
    }
}

const API_TROUBLESHOOTING = `- **Delivery shows Failing with a 401:** the token is a personal API key. Use your project token.
- **Delivery shows Healthy, but PostHog is empty:** check that the token comes from this project and that the region matches your PostHog cloud.
- **No prompts or responses:** the destination uses **Metadata only**. Organizations with a data-handling restriction, such as HIPAA, always export metadata only.`

const SDK_TROUBLESHOOTING = `- **No traces:** register the tracer provider before the first Claude call, and check that you installed the preview build. \`ANTHROPIC_OPEN_TELEMETRY=false\` turns the spans off.
- **Traces stop at the end of a script:** call \`provider.shutdown()\` before the script exits, so the last batch is sent.
- **No prompts or responses:** set the content mode to \`content\` on the client.
- **Each request appears twice:** a Claude Console destination also sends this project the same requests. Remove one of the two.`

export const getClaudePlatformSdkSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        getProjectTokenStep(ctx),
        {
            title: 'Install the Claude SDK preview build',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            During the beta, SDK tracing needs a preview build of the Claude SDK. Install it with the steps in Anthropic's [OpenTelemetry guide](${ANTHROPIC_OTEL_GUIDE}). Then install PostHog's span processor:
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install "posthog[otel]"
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai @opentelemetry/sdk-trace-node
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send the spans to PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Register a tracer provider with the processor before your first Claude call. Set the content
                        mode to see prompts and responses, because the SDK sends metadata only by default:
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from anthropic import Anthropic
                                    from opentelemetry import trace
                                    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
                                    from opentelemetry.sdk.trace import TracerProvider
                                    from posthog.ai.otel import PostHogSpanProcessor
    
                                    provider = TracerProvider(
                                        resource=Resource(attributes={SERVICE_NAME: "my-app"})
                                    )
                                    provider.add_span_processor(
                                        PostHogSpanProcessor(
                                            api_key="<ph_project_token>",
                                            host="<ph_client_api_host>",
                                        )
                                    )
                                    trace.set_tracer_provider(provider)
    
                                    client = Anthropic(open_telemetry={"content_mode": "content"})
    
                                    message = client.messages.create(
                                        model="claude-opus-5",
                                        max_tokens=1024,
                                        messages=[{"role": "user", "content": "Tell me about hedgehogs"}],
                                    )
    
                                    # Flush the batched spans before a script exits.
                                    provider.shutdown()
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import Anthropic from '@anthropic-ai/sdk'
                                    import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
                                    import { PostHogSpanProcessor } from '@posthog/ai/otel'
    
                                    const provider = new NodeTracerProvider({
                                      spanProcessors: [
                                        new PostHogSpanProcessor({
                                          projectToken: '<ph_project_token>',
                                          host: '<ph_client_api_host>',
                                        }),
                                      ],
                                    })
                                    provider.register()
    
                                    const client = new Anthropic({ openTelemetry: { contentMode: 'content' } })
    
                                    const message = await client.messages.create({
                                      model: 'claude-opus-5',
                                      max_tokens: 1024,
                                      messages: [{ role: 'user', content: 'Tell me about hedgehogs' }],
                                    })
    
                                    // Flush the batched spans before a script exits.
                                    await provider.shutdown()
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            Use SDK tracing or a Claude Console destination for a project, not both. With both, each request reaches PostHog twice.
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Call Claude and see the trace',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        Run your app. Each Claude call shows up in [AI Observability](https://app.posthog.com/ai-observability/traces) as an \`anthropic.messages.create\` trace, with its cost, tokens, and messages. If you use the tool runner, each tool it runs gets its own span.
                    `}
                </Markdown>
            ),
        },
        getTroubleshootingStep(ctx, SDK_TROUBLESHOOTING),
    ]
}

export const getClaudePlatformApiSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, ProductScreenshot, dedent } = ctx

    return [
        getProjectTokenStep(ctx),
        getAddDestinationStep(ctx),
        {
            title: 'Call Claude and see the trace',
            badge: 'required',
            content: (
                <>
                    <Markdown>Call the Messages API the way you already do. Your code doesn't change:</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import anthropic

                                    client = anthropic.Anthropic()

                                    message = client.messages.create(
                                        model="claude-opus-5",
                                        max_tokens=1024,
                                        messages=[{"role": "user", "content": "Tell me about hedgehogs"}],
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import Anthropic from '@anthropic-ai/sdk'

                                    const client = new Anthropic()

                                    const message = await client.messages.create({
                                      model: 'claude-opus-5',
                                      max_tokens: 1024,
                                      messages: [{ role: 'user', content: 'Tell me about hedgehogs' }],
                                    })
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            Open [AI Observability](https://app.posthog.com/ai-observability/traces). Each request is one trace: the \`anthropic.messages.create\` generation, with its cost, tokens, and messages, and the \`anthropic.model_request\` span inside it.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            **Using Managed Agents?** Each message you send to a session becomes one trace, with a span for each turn, model request, and tool use:
                        `}
                    </Markdown>

                    <ProductScreenshot
                        imageLight={MANAGED_AGENTS_TRACE_SCREENSHOT}
                        imageDark={MANAGED_AGENTS_TRACE_SCREENSHOT}
                        alt="A Managed Agents trace in PostHog: session turns with model requests and bash tool uses on a timeline, and the turn input and output"
                        classes="rounded"
                    />

                    <Markdown>
                        {dedent`
                            The turn holds the agent's input and output, each model request holds its tokens and cost, and each tool use holds its arguments and result. To follow one session across turns, filter by \`anthropic.session.id\`.
                        `}
                    </Markdown>
                </>
            ),
        },
        getTroubleshootingStep(ctx, API_TROUBLESHOOTING),
    ]
}

export const ClaudePlatformApiInstallation = createInstallation(getClaudePlatformApiSteps)
export const ClaudePlatformSdkInstallation = createInstallation(getClaudePlatformSdkSteps)
