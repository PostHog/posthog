import { IconArrowRight, IconList } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

type WarehouseFinding = {
    title: string
    description: string
    source: string
}

type ContextWarehouseFindingsProps = {
    findings: WarehouseFinding[]
    onOpenInbox: (finding: WarehouseFinding) => void
}

export function ContextWarehouseFindings({ findings, onOpenInbox }: ContextWarehouseFindingsProps): JSX.Element {
    return (
        <div className="@container/context-warehouse-findings space-y-4">
            <div>
                <div className="flex flex-wrap items-center gap-2">
                    <IconList />
                    <h2 className="mb-0">Warehouse findings</h2>
                    <LemonBadge.Number count={findings.length} maxDigits={2} />
                </div>
                <p className="mb-0 mt-1 max-w-3xl text-secondary">
                    Signals detected these findings across warehouse sources, models, quality checks, and freshness.
                    Open Inbox to review, assign, or resolve them.
                </p>
            </div>

            <div className="grid grid-cols-1 gap-3 @min-[48rem]/context-warehouse-findings:grid-cols-2">
                {findings.map((finding) => (
                    <LemonCard key={finding.title} className="flex flex-col gap-3 p-4" hoverEffect={false}>
                        <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                                <h3 className="mb-0 text-base">{finding.title}</h3>
                                <LemonTag size="small">{finding.source}</LemonTag>
                            </div>
                            <p className="mb-0 mt-2 text-sm text-secondary">{finding.description}</p>
                        </div>
                        <div>
                            <LemonButton
                                data-attr={`context-warehouse-finding-${finding.title
                                    .toLowerCase()
                                    .replace(/[^a-z0-9]+/g, '-')}`}
                                icon={<IconArrowRight />}
                                onClick={() => onOpenInbox(finding)}
                                size="small"
                                type="secondary"
                            >
                                Open in Inbox
                            </LemonButton>
                        </div>
                    </LemonCard>
                ))}
            </div>
        </div>
    )
}
