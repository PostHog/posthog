## Shared onboarding docs

This directory contains shared onboarding docs that are used in the:
- In product onboarding process.
- Imported by Gatsby build to be published on posthog.com.
- Used by the PostHog Wizard and MCP (soon™️)

## Component context

Since these files are shared between the frontend and the docs, we need to pass the locally available version of the **components** and **snippets** to the shared docs.

To do this, we use the `OnboardingDocsContentWrapper` component in `frontend/src/scenes/onboarding/OnboardingDocsContentWrapper.tsx`. This component is a wrapper that passes the locally available version of the components to the shared docs.

For example, in `frontend/src/scenes/onboarding/sdks/llm-analytics/LLMAnalyticsSDKInstructions.tsx`, we pass the locally available version of the components and snippets to the shared docs like this:

```tsx
const snippets = {
    GenerationEvent,
    TraceEvent,
    SpanEvent,
    EmbeddingEvent,
}

<OnboardingDocsContentWrapper snippets={snippets}>
    <ManualInstallation />
</OnboardingDocsContentWrapper>
```

This allows the shared docs to use the locally available version of the components and snippets.

## Authoring shared docs

When authoring a shared doc, you can use the locally available version of the components and snippets. For example, `frontend/src/scenes/onboarding/shared-docs/llm-analytics/anthropic.tsx` uses the `useMDXComponents` hook to get the locally available version of the components and snippets.

```tsx
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const AnthropicInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, CalloutBox, ProductScreenshot, OSButton, Markdown, Blockquote, dedent, snippets } =
        useMDXComponents()

    const NotableGenerationProperties = snippets?.NotableGenerationProperties
    return (
        <Steps>
            <Step title="Install the PostHog SDK" badge="required">
                <Markdown>
                    {dedent`
                        Setting up analytics starts with installing the PostHog SDK for your language. LLM analytics works
                        best with our Python and Node SDKs.
                    `}
                </Markdown>

                <CodeBlock ...> {...} <CodeBlock />
                // more code...
            </Step>
        </Steps>
    )
}
```

You can author prose content using the `Markdown` component that supports vanilla Markdown and dedent strings, or directly with html prose.

## Previews and syncing with posthog.com

When you update a file in the `frontend/src/scenes/onboarding/shared-docs` directory, a GitHub Actions workflow (`.github/workflows/docs-preview-trigger.yml`) will automatically trigger a preview build of the docs. 

The website, when building, will pull the posthog monorepo and link the `frontend/src/scenes/onboarding/shared-docs` directory with Gatsby to build the docs.

You will need to use MDX stubs to import the shared docs into the website.