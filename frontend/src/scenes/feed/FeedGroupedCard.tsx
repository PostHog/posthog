import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { FeedItemRow } from './FeedItemRow'
import { FeedItem } from './feedLogic'

interface FeedGroupedCardProps {
    items: FeedItem[]
    config: {
        title: string
        icon: JSX.Element
        color: string
        borderColor: string
    }
}

function getSummaryText(items: FeedItem[]): string {
    if (items.length <= 3) {
        return items.map((item) => item.name).join(', ')
    }

    // Show first 2 items and count of remaining
    const firstTwo = items.slice(0, 2).map((item) => item.name)
    const remaining = items.length - 2
    return `${firstTwo.join(', ')} and ${remaining} more`
}

export function FeedGroupedCard({ items, config }: FeedGroupedCardProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    if (items.length === 0) {
        return <></>
    }

    // Single item - show directly without grouping
    if (items.length === 1) {
        return <FeedItemRow item={items[0]} config={config} />
    }

    // Multiple items - show collapsible group
    return (
        <div
            className="border rounded border-l-4 overflow-hidden"
            style={{ borderLeftColor: config.borderColor }}
            data-attr={`feed-group-${items[0]?.type || 'unknown'}`}
        >
            <div
                className="p-4 bg-bg-light hover:bg-bg-3000 cursor-pointer transition-all group"
                onClick={() => setIsExpanded(!isExpanded)}
                data-attr={`feed-group-toggle-${items[0]?.type || 'unknown'}`}
            >
                <div className="flex items-center justify-between gap-2">
                    <div className="flex-1 flex items-center gap-3 min-w-0">
                        <div className="flex-shrink-0" style={{ color: config.color }}>
                            {config.icon}
                        </div>
                        <span className="font-semibold flex-shrink-0" style={{ color: config.color }}>
                            {items.length} {config.title}
                        </span>
                        <span className="text-muted text-sm truncate">{getSummaryText(items)}</span>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-xs text-muted group-hover:text-default transition-colors">
                            {isExpanded ? 'Collapse' : 'Expand'}
                        </span>
                        <IconChevronDown className={`text-lg transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                    </div>
                </div>
            </div>

            {isExpanded && (
                <div className="border-t border-border">
                    <div className="p-4 space-y-4 bg-bg-3000">
                        {items.map((item) => (
                            <FeedItemRow key={`${item.type}-${item.id}`} item={item} config={config} />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
