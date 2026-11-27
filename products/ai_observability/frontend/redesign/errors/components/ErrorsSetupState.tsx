import { LemonButton } from '@posthog/lemon-ui'

const ERRORS_DOCS_URL = 'https://posthog.com/docs/ai-observability/errors'

export interface ErrorsSetupStateProps {
    tracesHref: string
    'data-attr': string
}

export function ErrorsSetupState({ tracesHref, 'data-attr': dataAttr }: ErrorsSetupStateProps): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
            <h3 className="m-0 text-sm font-semibold text-primary">No errors captured yet</h3>
            <p className="m-0 max-w-120 text-secondary">
                Errors show here once your AI events report failed calls. PostHog's SDK wrappers mark a failed LLM call
                as an error for you. If you capture events yourself, set <code>$ai_is_error</code> to true and{' '}
                <code>$ai_error</code> to the error message.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={ERRORS_DOCS_URL}
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
