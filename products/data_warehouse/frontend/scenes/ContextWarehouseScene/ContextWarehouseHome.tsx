import { IconArrowRight, IconWarning } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

type HealthCard = {
    title: string
    value: string
    description: string
    status: 'success' | 'warning'
}

type AttentionItem = {
    title: string
    description: string
    source: string
    actionLabel: string
}

type ContextWarehouseHomeProps = {
    healthCards: HealthCard[]
    attentionItems: AttentionItem[]
    onOpenSqlEditor: () => void
    onAttentionAction: (item: AttentionItem) => void
}

export function ContextWarehouseHome({
    healthCards,
    attentionItems,
    onOpenSqlEditor,
    onAttentionAction,
}: ContextWarehouseHomeProps): JSX.Element {
    return (
        <div className="@container/context-warehouse-home space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 max-w-3xl">
                    <div className="flex flex-wrap items-center gap-2">
                        <h2 className="mb-0">Warehouse health</h2>
                        <LemonTag type="warning">Needs attention</LemonTag>
                    </div>
                    <p className="mb-0 mt-1 text-secondary">
                        See the health of sources, models, quality checks, and freshness in one place.
                    </p>
                </div>
                <LemonButton
                    data-attr="context-warehouse-open-sql-editor"
                    icon={<IconArrowRight />}
                    onClick={onOpenSqlEditor}
                    type="primary"
                >
                    Open SQL editor
                </LemonButton>
            </div>

            <div className="grid grid-cols-1 gap-3 @min-[36rem]/context-warehouse-home:grid-cols-2 @min-[52rem]/context-warehouse-home:grid-cols-4">
                {healthCards.map((card) => (
                    <LemonCard key={card.title} className="space-y-2 p-4" hoverEffect={false}>
                        <div className="flex items-center justify-between gap-2">
                            <h3 className="mb-0 text-sm font-semibold">{card.title}</h3>
                            <LemonBadge status={card.status} size="small" />
                        </div>
                        <div className="text-xl font-semibold">{card.value}</div>
                        <p className="mb-0 text-sm text-secondary">{card.description}</p>
                    </LemonCard>
                ))}
            </div>

            <section className="space-y-3" aria-labelledby="context-warehouse-attention-heading">
                <div>
                    <div className="flex flex-wrap items-center gap-2">
                        <IconWarning className="text-warning" />
                        <h2 id="context-warehouse-attention-heading" className="mb-0 text-lg">
                            Needs attention
                        </h2>
                        <LemonBadge.Number count={attentionItems.length} maxDigits={2} status="warning" />
                    </div>
                    <p className="mb-0 mt-1 text-sm text-secondary">
                        These findings come from Signals. Open Inbox to review, assign, or resolve them.
                    </p>
                </div>
                <div className="divide-y rounded border bg-surface-primary">
                    {attentionItems.map((item) => (
                        <div
                            key={item.title}
                            className="flex flex-col gap-3 p-4 @min-[40rem]/context-warehouse-home:flex-row @min-[40rem]/context-warehouse-home:items-center @min-[40rem]/context-warehouse-home:justify-between"
                        >
                            <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                    <h3 className="mb-0 text-sm font-semibold">{item.title}</h3>
                                    <LemonTag size="small">{item.source}</LemonTag>
                                </div>
                                <p className="mb-0 mt-1 text-sm text-secondary">{item.description}</p>
                            </div>
                            <LemonButton
                                data-attr={`context-warehouse-attention-${item.title
                                    .toLowerCase()
                                    .replace(/[^a-z0-9]+/g, '-')}`}
                                onClick={() => onAttentionAction(item)}
                                size="small"
                                type="secondary"
                            >
                                {item.actionLabel}
                            </LemonButton>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    )
}
