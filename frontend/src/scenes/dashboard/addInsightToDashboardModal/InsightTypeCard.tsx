import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { InsightTypeMetadata } from 'scenes/saved-insights/SavedInsights'

interface InsightTypeCardProps {
    type: string
    metadata: InsightTypeMetadata
    to: string
    className?: string
}

export function InsightTypeCard({ type, metadata, to, className }: InsightTypeCardProps): JSX.Element {
    const Icon = metadata.icon

    return (
        <Link
            to={to}
            className={cn(
                'block p-4 rounded-lg border border-primary bg-surface-primary',
                'hover:border-accent-dark hover:bg-surface-secondary transition-colors',
                'no-underline',
                className
            )}
            data-attr={`insight-type-card-${type.toLowerCase()}`}
        >
            <div className="flex items-start gap-3">
                {Icon && (
                    <div className="shrink-0 text-2xl text-secondary">
                        <Icon />
                    </div>
                )}
                <div className="flex-1 min-w-0">
                    <div className="font-semibold text-default">{metadata.name}</div>
                    {metadata.description && (
                        <div className="text-xs text-secondary mt-0.5 line-clamp-2">{metadata.description}</div>
                    )}
                </div>
            </div>
        </Link>
    )
}
