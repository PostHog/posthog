import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOtelRequestContextStep } from './_snippets/otel-request-context'

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

const ConsoleDestination = ({ ctx }: { ctx: OnboardingComponentsContext }): JSX.Element => {
    const { CalloutBox, Markdown, ProductScreenshot, dedent } = ctx

    return (
        <>
            <CalloutBox type="fyi" icon="IconInfo">
                <Markdown>
                    API tracing does not yet support person identification or custom properties. Anthropic is exploring
                    ways to support this in the future.
                </Markdown>
            </CalloutBox>

            <Markdown>
                {dedent`
                    In the Claude Console, open the [OpenTelemetry settings](https://platform.claude.com/settings/telemetry-destinations) of your organization and click **Add destination**. You need an admin role.

                    1. **Provider:** PostHog.
                    2. **Region:** US if you log in at \`us.posthog.com\`, EU if you log in at \`eu.posthog.com\`.
                    3. **Project token:** paste your \`phc_\` token.
                    4. **Content mode:** pick **Full content** to see every prompt and response in PostHog. **Metadata only** sends tokens, costs, and timing without the messages.
                    5. **Workspaces:** choose which workspaces send their traces to PostHog: **All**, **Selected**, or **All except**.
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
                    Click **Add destination**. Your code doesn't change.

                    Anthropic's [OpenTelemetry guide](${ANTHROPIC_OTEL_GUIDE}) covers workspaces, delivery health, and every span and attribute.
                `}
            </Markdown>
        </>
    )
}

const PYTHON_SETUP = `
from anthropic import Anthropic
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from posthog.ai.otel import PostHogSpanProcessor

resource = Resource(attributes={
    SERVICE_NAME: "my-app",
    "posthog.distinct_id": "user_123", # optional: identifies the user in PostHog
    "foo": "bar", # custom properties are passed through
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(
    PostHogSpanProcessor(
        api_key="<ph_project_token>",
        host="<ph_client_api_host>",
    )
)
trace.set_tracer_provider(provider)

client = Anthropic(open_telemetry={"traces": {"content_mode": "content"}})

message = client.messages.create(
    model="claude-opus-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Tell me about hedgehogs"}],
)

# Flush the batched spans before a script exits.
provider.shutdown()
`.trim()

const NODE_SETUP = `
import Anthropic from '@anthropic-ai/sdk'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
import { PostHogSpanProcessor } from '@posthog/ai/otel'

const provider = new NodeTracerProvider({
  resource: resourceFromAttributes({
    'service.name': 'my-app',
    'posthog.distinct_id': 'user_123', // optional: identifies the user in PostHog
    foo: 'bar', // custom properties are passed through
  }),
  spanProcessors: [
    new PostHogSpanProcessor({
      projectToken: '<ph_project_token>',
      host: '<ph_client_api_host>',
    }),
  ],
})
provider.register()

const client = new Anthropic({ openTelemetry: { traces: { contentMode: 'content' } } })

const message = await client.messages.create({
  model: 'claude-opus-5',
  max_tokens: 1024,
  messages: [{ role: 'user', content: 'Tell me about hedgehogs' }],
})

// Flush the batched spans before a script exits.
await provider.shutdown()
`.trim()

const GO_SETUP = `
package main

import (
    "context"
    "fmt"

    "github.com/anthropics/anthropic-sdk-go"
    "github.com/anthropics/anthropic-sdk-go/option"
    posthogotel "github.com/posthog/posthog-go/otel"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/propagation"
    sdkresource "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func main() {
    ctx := context.Background()

    processor, err := posthogotel.NewSpanProcessor(ctx, "<ph_project_token>",
        posthogotel.WithHost("<ph_client_api_host>"),
    )
    if err != nil {
        panic(err)
    }

    resource := sdkresource.NewWithAttributes("",
        attribute.String("service.name", "my-app"),
        attribute.String("posthog.distinct_id", "user_123"), // optional: identifies the user in PostHog
        attribute.String("foo", "bar"), // custom properties are passed through
    )
    provider := sdktrace.NewTracerProvider(
        sdktrace.WithResource(resource),
        sdktrace.WithSpanProcessor(processor),
    )
    // Flush the batched spans before the program exits.
    defer provider.Shutdown(ctx)
    otel.SetTracerProvider(provider)
    otel.SetTextMapPropagator(propagation.TraceContext{})

    client := anthropic.NewClient(
        option.WithOpenTelemetryTracesContentMode(option.OpenTelemetryContentModeContent),
    )

    message, err := client.Messages.New(ctx, anthropic.MessageNewParams{
        Model:     anthropic.ModelClaudeOpus5,
        MaxTokens: 1024,
        Messages: []anthropic.MessageParam{
            anthropic.NewUserMessage(anthropic.NewTextBlock("Tell me about hedgehogs")),
        },
    })
    if err != nil {
        panic(err)
    }
    fmt.Println(message.StopReason)
}
`.trim()

const JAVA_SETUP = `
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import com.anthropic.core.opentelemetry.OpenTelemetryContentMode;
import com.anthropic.core.opentelemetry.OpenTelemetryOptions;
import com.anthropic.models.messages.MessageCreateParams;
import com.anthropic.models.messages.Model;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;

public class Main {
    public static void main(String[] args) {
        var exporter = OtlpHttpSpanExporter.builder()
            .setEndpoint("<ph_client_api_host>/i/v0/ai/otel")
            .addHeader("Authorization", "Bearer <ph_project_token>")
            .build();

        var resource = Resource.getDefault().merge(Resource.create(Attributes.of(
            AttributeKey.stringKey("service.name"), "my-app",
            AttributeKey.stringKey("posthog.distinct_id"), "user_123", // optional: identifies the user in PostHog
            AttributeKey.stringKey("foo"), "bar"))); // custom properties are passed through

        var tracerProvider = SdkTracerProvider.builder()
            .setResource(resource)
            .addSpanProcessor(BatchSpanProcessor.builder(exporter).build())
            .build();
        OpenTelemetrySdk.builder()
            .setTracerProvider(tracerProvider)
            .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
            .buildAndRegisterGlobal();

        var envOptions = OpenTelemetryOptions.fromEnv();
        var client = AnthropicOkHttpClient.builder()
            .fromEnv()
            .openTelemetry(envOptions.toBuilder()
                .traces(envOptions.traces().toBuilder()
                    .contentMode(OpenTelemetryContentMode.CONTENT)
                    .build())
                .build())
            .build();

        var message = client.messages().create(MessageCreateParams.builder()
            .model(Model.CLAUDE_OPUS_5)
            .maxTokens(1024)
            .addUserMessage("Tell me about hedgehogs")
            .build());

        // Flush the batched spans before the program exits.
        tracerProvider.close();
    }
}
`.trim()

const RUBY_SETUP = `
require "anthropic"
require "opentelemetry/sdk"
require "opentelemetry/exporter/otlp"

OpenTelemetry::SDK.configure do |config|
  config.resource = OpenTelemetry::SDK::Resources::Resource.create(
    "service.name" => "my-app",
    "posthog.distinct_id" => "user_123", # optional: identifies the user in PostHog
    "foo" => "bar" # custom properties are passed through
  )
  config.add_span_processor(
    OpenTelemetry::SDK::Trace::Export::BatchSpanProcessor.new(
      OpenTelemetry::Exporter::OTLP::Exporter.new(
        endpoint: "<ph_client_api_host>/i/v0/ai/otel",
        headers: {"Authorization" => "Bearer <ph_project_token>"}
      )
    )
  )
end

client = Anthropic::Client.new(open_telemetry: {traces: {content_mode: :content}})

message = client.messages.create(
  model: Anthropic::Model::CLAUDE_OPUS_5,
  max_tokens: 1024,
  messages: [{role: "user", content: "Tell me about hedgehogs"}]
)

# Flush the batched spans before a script exits.
OpenTelemetry.tracer_provider.shutdown
`.trim()

const JAVA_INSTALL = `
dependencies {
    implementation(platform("io.opentelemetry:opentelemetry-bom:1.57.0"))
    implementation("io.opentelemetry:opentelemetry-sdk")
    implementation("io.opentelemetry:opentelemetry-exporter-otlp")
}
`.trim()

const SdkTracing = ({ ctx }: { ctx: OnboardingComponentsContext }): JSX.Element => {
    const { CodeBlock, Markdown, dedent } = ctx

    return (
        <>
            <Markdown>
                {dedent`
                    Install the Claude SDK with the steps in Anthropic's [OpenTelemetry guide](${ANTHROPIC_OTEL_GUIDE}/sdk#install-the-sdk). Then install the OpenTelemetry packages. PostHog has a span processor for Python, Node, and Go. Java and Ruby use the standard OTLP exporter.
                `}
            </Markdown>

            <CodeBlock
                blocks={[
                    { language: 'bash', file: 'Python', code: 'pip install "posthog[otel]"' },
                    {
                        language: 'bash',
                        file: 'Node',
                        code: 'npm install @posthog/ai @opentelemetry/sdk-trace-node @opentelemetry/resources @opentelemetry/exporter-trace-otlp-http',
                    },
                    {
                        language: 'bash',
                        file: 'Go',
                        code: 'go get github.com/posthog/posthog-go/otel go.opentelemetry.io/otel go.opentelemetry.io/otel/sdk',
                    },
                    { language: 'kotlin', file: 'Java', code: JAVA_INSTALL },
                    {
                        language: 'bash',
                        file: 'Ruby',
                        code: 'bundle add opentelemetry-sdk opentelemetry-exporter-otlp',
                    },
                ]}
            />

            <Markdown>
                Register a tracer provider before your first Claude call. Set the content mode to see prompts and
                responses, because the SDK sends metadata only by default:
            </Markdown>

            <CodeBlock
                blocks={[
                    { language: 'python', file: 'Python', code: PYTHON_SETUP },
                    { language: 'typescript', file: 'Node', code: NODE_SETUP },
                    { language: 'go', file: 'Go', code: GO_SETUP },
                    { language: 'java', file: 'Java', code: JAVA_SETUP },
                    { language: 'ruby', file: 'Ruby', code: RUBY_SETUP },
                ]}
            />

            <Markdown>
                {dedent`
                    You can also set the content mode with the \`ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE=content\` environment variable.

                    To group several calls into one session, set a conversation ID on the client or the request, as described in [Configure the SDK](${ANTHROPIC_OTEL_GUIDE}/sdk#configure-the-sdk). PostHog uses it as the session ID.
                `}
            </Markdown>
        </>
    )
}

const getSendTracesStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown, Tab, dedent } = ctx

    return {
        title: 'Choose how to send traces',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        The Claude Platform can send traces from two places. Pick one for each PostHog project. If you use both, each request reaches PostHog twice.

                        - **SDK tracing:** you set it up in your code with the Claude SDK. It covers the calls your app makes and the tools it runs itself. You can link traces to your users and add custom properties.
                        - **Console destination:** you add PostHog in the Claude Console, with no code changes. It covers your Messages API requests, server tools such as web search, and Managed Agents sessions.
                    `}
                </Markdown>

                <Tab.Group tabs={['SDK tracing', 'Console destination']}>
                    <Tab.List>
                        <Tab>SDK tracing</Tab>
                        <Tab>Console destination</Tab>
                    </Tab.List>
                    <Tab.Panels>
                        <Tab.Panel>
                            <SdkTracing ctx={ctx} />
                        </Tab.Panel>
                        <Tab.Panel>
                            <ConsoleDestination ctx={ctx} />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
            </>
        ),
    }
}

const getRequestContextStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown } = ctx
    const step = getOtelRequestContextStep(ctx, {
        languages: ['Python', 'Node', 'Go'],
        nodeTracerSetup: 'NodeTracerProvider',
    })

    return {
        ...step,
        content: (
            <>
                <Markdown>This step applies to SDK tracing in Python, Node, and Go.</Markdown>
                {step.content}
            </>
        ),
    }
}

const getSeeTraceStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown, ProductScreenshot, dedent } = ctx

    return {
        title: 'Call Claude and see the trace',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Call Claude the way you already do, then open [AI Observability](https://app.posthog.com/ai-observability/traces). Each request shows up as an \`anthropic.messages.create\` trace, with its cost, tokens, and messages.

                        - **SDK tracing:** if you use the tool runner, each tool it runs gets its own span.
                        - **Console destination:** the trace holds an \`anthropic.model_request\` span for each model request. A request can have more than one, for example when the model uses web search.

                        **Using Managed Agents?** A Console destination also sends your sessions, with a span for each turn, model request, and tool use:
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
                        The turn holds the agent's input and output, each model request holds its tokens and cost, and each tool use holds its arguments and result. A session can span several traces. To follow one session, filter by \`anthropic.session.id\`.
                    `}
                </Markdown>
            </>
        ),
    }
}

const TROUBLESHOOTING = `- **Delivery shows Failing with a 401:** the token in the Claude Console is a personal API key. Use your project token.
- **Delivery shows Healthy, but PostHog is empty:** check that the token comes from this project and that the region matches your PostHog cloud.
- **No traces from a Console destination:** check that the destination's **Workspaces** setting covers the workspace of your API key. Traces can take up to a minute to arrive.
- **No traces from the Claude SDK:** register the tracer provider before the first Claude call. \`ANTHROPIC_OPEN_TELEMETRY=false\` turns the spans off.
- **Traces stop at the end of a script:** shut down the tracer provider before the script exits, as the samples do, so the last batch is sent.
- **No prompts or responses:** in the Claude Console, the destination uses **Metadata only**. Organizations with a data-handling restriction, such as HIPAA, always export metadata only. With the Claude SDK, set the content mode to \`content\` on the client.
- **Each request appears twice:** a Claude Console destination and the Claude SDK both send this project the same requests. Remove one of the two.`

const getTroubleshootingStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { Markdown } = ctx

    return {
        title: 'Troubleshooting',
        badge: 'optional',
        content: (
            <Markdown>
                {`${TROUBLESHOOTING}\n\nFor other questions, see [AI Observability troubleshooting](https://posthog.com/docs/ai-observability/troubleshooting).`}
            </Markdown>
        ),
    }
}

export const getClaudePlatformSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    getProjectTokenStep(ctx),
    getSendTracesStep(ctx),
    getSeeTraceStep(ctx),
    getRequestContextStep(ctx),
    getTroubleshootingStep(ctx),
]

export const ClaudePlatformInstallation = createInstallation(getClaudePlatformSteps)
