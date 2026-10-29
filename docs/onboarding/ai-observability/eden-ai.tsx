import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { getOpenAICompatibleSteps } from './_snippets/openai-compatible'

export const getEdenAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, Blockquote, dedent } = ctx

    return getOpenAICompatibleSteps(ctx, {
        label: 'Eden AI',
        slug: 'eden-ai',
        baseUrl: 'https://api.edenai.run/v3',
        apiKeyPlaceholder: '<eden_ai_api_key>',
        defaultModel: 'openai/gpt-5.5',
        exampleRepos: false,
        configureNote: (
            <Blockquote>
                <Markdown>
                    **Note:** To keep requests in Europe, use Eden AI's EU endpoint `https://api.eu.edenai.run/v3` as
                    the base URL. It only accepts providers and models cleared for EU data residency and rejects other
                    models with HTTP 451. See [Eden AI's EU endpoint
                    docs](https://www.edenai.co/docs/v3/data-governance/eu-endpoint) for the current list.
                </Markdown>
            </Blockquote>
        ),
        callNote: (
            <Markdown>
                {dedent`
                    Eden AI model IDs include the provider, for example \`openai/gpt-5.5\` or
                    \`anthropic/claude-sonnet-4-6\`. PostHog stores the ID as \`$ai_model\` and looks it up in its
                    price list, with and without the provider prefix, to fill \`$ai_total_cost_usd\`. IDs that are
                    not in the list, such as the \`openai/gpt-latest\` alias, get no cost. See [Eden AI's model
                    list](https://www.edenai.co/docs/v3/llms/listing-models) for the available IDs.

                    The examples below pass a \`tools\` list in OpenAI's function-calling format and, in the next
                    step, call a \`run_tool\` or \`runTool\` helper. Define both for your own tools.
                `}
            </Markdown>
        ),
    })
}

export const EdenAIInstallation = createInstallation(getEdenAISteps)
