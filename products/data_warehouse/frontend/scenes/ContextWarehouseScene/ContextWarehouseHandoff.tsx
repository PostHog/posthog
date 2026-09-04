import { IconDatabase } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonTag } from '@posthog/lemon-ui'

type ContextWarehouseHandoffProps = {
    title: string
    description: string
    details: string[]
}

export function ContextWarehouseHandoff({ title, description, details }: ContextWarehouseHandoffProps): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonBanner type="info">
                This production screen would move under Context warehouse without changing its core workflow.
            </LemonBanner>
            <LemonCard className="space-y-4 p-4" hoverEffect={false}>
                <div className="flex flex-wrap items-center gap-2">
                    <IconDatabase />
                    <h2 className="mb-0">{title}</h2>
                    <LemonTag size="small">Existing screen</LemonTag>
                </div>
                <p className="mb-0 text-secondary">{description}</p>
                <div className="grid grid-cols-1 gap-2 @min-[42rem]/context-warehouse:grid-cols-3">
                    {details.map((detail) => (
                        <div key={detail} className="rounded border bg-surface-secondary px-3 py-2 text-sm font-medium">
                            {detail}
                        </div>
                    ))}
                </div>
            </LemonCard>
        </div>
    )
}
