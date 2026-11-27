import { LemonButton } from '@posthog/lemon-ui'

const TOOLS_DOCS_URL = 'https://posthog.com/docs/ai-observability/tools'

export interface ToolsSetupStateProps {
    tracesHref: string
    'data-attr': string
}

export function ToolsSetupState({ tracesHref, 'data-attr': dataAttr }: ToolsSetupStateProps): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
            <h3 className="m-0 text-sm font-semibold text-primary">No tool calls captured yet</h3>
            <p className="m-0 max-w-120 text-secondary">
                Tools show here once your generations call them. PostHog's SDK wrappers record the tools a model calls
                for you. Failures show once your app sends the tool results back to the model.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={TOOLS_DOCS_URL}
                    targetBlank
                    data-attr={`${dataAttr}-setup-docs`}
                >
                    Read the docs
                </LemonButton>
                <LemonButton type="secondary" size="small" to={tracesHref} data-attr={`${dataAttr}-setup-traces`}>
                    View traces instead
                </LemonButton>
            </div>
        </div>
    )
}
