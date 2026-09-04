import { IconSparkles } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Composer, Thread } from 'products/posthog_ai/frontend/api/primitives'

type ContextWarehouseAiPanelProps = {
    composerValue: string
    onComposerChange: (value: string) => void
    onComposerSubmit: () => void
}

export function ContextWarehouseAiPanel({
    composerValue,
    onComposerChange,
    onComposerSubmit,
}: ContextWarehouseAiPanelProps): JSX.Element {
    return (
        <aside
            className="flex min-h-0 flex-col rounded border bg-surface-primary"
            aria-label="PostHog AI query assistant"
        >
            <div className="flex items-center gap-2 border-b px-3 py-2">
                <IconSparkles className="text-ai" />
                <h3 className="mb-0 text-sm font-semibold">PostHog AI</h3>
            </div>
            <div className="flex flex-1 flex-col gap-3 p-3">
                <Thread.Message type="human" header={<span className="sr-only">You</span>}>
                    Compare monthly and annual revenue for the last seven days.
                </Thread.Message>
                <Thread.Message type="ai" header={<span className="sr-only">PostHog AI</span>}>
                    Annual plans account for most of the drop. I prepared a query that compares billing intervals before
                    aggregation.
                </Thread.Message>
            </div>
            <div className="border-t p-3">
                <Composer.Root value={composerValue} onChange={onComposerChange} onSubmit={onComposerSubmit}>
                    <Composer.Frame>
                        <Composer.Header>
                            <LemonTag size="small" icon={<IconSparkles />}>
                                Revenue by billing interval
                            </LemonTag>
                        </Composer.Header>
                        <Composer.Field>
                            <Composer.Placeholder>Ask PostHog AI about this query</Composer.Placeholder>
                            <Composer.Textarea data-attr="context-warehouse-ai-composer" minRows={2} maxRows={5} />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit data-attr="context-warehouse-ai-submit" tooltip="Send message" />
                </Composer.Root>
            </div>
        </aside>
    )
}
