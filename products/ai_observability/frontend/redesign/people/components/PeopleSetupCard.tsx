import { LemonButton } from '@posthog/lemon-ui'

export interface PeopleSetupCardProps {
    docsUrl: string
    tracesHref: string
}

export function PeopleSetupCard({ docsUrl, tracesHref }: PeopleSetupCardProps): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
            <h3 className="m-0 text-sm font-semibold text-primary">Link traces to people</h3>
            <p className="m-0 max-w-120 text-secondary">
                Every person in this date range is anonymous. Send <code>posthog_distinct_id</code> with your LLM calls
                to link each trace to the person who made it, or turn on Include anonymous to list them as they are.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    to={docsUrl}
                    targetBlank
                    // pinned: autocapture dashboards and tests select the setup card's actions by these values
                    data-attr="ai-observability-people-setup-docs"
                >
                    Read the docs
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={tracesHref}
                    data-attr="ai-observability-people-setup-traces"
                >
                    View traces instead
                </LemonButton>
            </div>
        </div>
    )
}
