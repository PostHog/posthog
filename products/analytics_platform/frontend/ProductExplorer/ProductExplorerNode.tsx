import './ProductExplorer.scss'

import {
    IconAI,
    IconBolt,
    IconDatabase,
    IconGear,
    IconGraph,
    IconMessage,
    IconMegaphone,
    IconPeople,
    IconPieChart,
    IconRetentionHeatmap,
    IconRewindPlay,
    IconRocket,
    IconTestTube,
    IconToggle,
    IconTrending,
    IconWarning,
} from '@posthog/icons'
import clsx from 'clsx'

import type { ProductNodeStatus, ProductTreeNode } from './productTreeData'

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
    IconBolt,
    IconGraph,
    IconPieChart,
    IconRewindPlay,
    IconWarning,
    IconRetentionHeatmap,
    IconMessage,
    IconToggle,
    IconTestTube,
    IconRocket,
    IconAI,
    IconDatabase,
    IconGear,
    IconTrending,
    IconPeople,
    IconMegaphone,
    IconHeatmap: IconRetentionHeatmap,
}

export interface ProductExplorerNodeData extends ProductTreeNode {
    status: ProductNodeStatus
    usagePercent?: number
    usageLabel?: string
    freeAllocation?: string
    justUnlocked?: boolean
}

function iconStyle(data: ProductExplorerNodeData): React.CSSProperties {
    if (data.status === 'unlocked' || data.id === 'events_core') {
        return { background: data.color, color: 'white' }
    }
    if (data.status === 'coming_soon') {
        return {}
    }
    // Available: tinted background with colored icon
    return { background: `color-mix(in srgb, ${data.color} 18%, transparent)`, color: data.color }
}

export function ProductExplorerNode({
    data,
    onClick,
    selected,
}: {
    data: ProductExplorerNodeData
    onClick?: () => void
    selected?: boolean
}): JSX.Element {
    const IconComponent = ICON_MAP[data.iconName] || IconBolt
    const isCore = data.id === 'events_core'
    const isUnlocked = data.status === 'unlocked'
    const isComingSoon = data.status === 'coming_soon'

    const meta = isUnlocked
        ? data.usageLabel
        : isComingSoon
          ? 'Coming soon'
          : data.freeTier
            ? `${data.freeTier} free`
            : undefined

    // Show usage bar for unlocked (actual usage) and available with free tier (empty bar)
    const hasUsageBar = (isUnlocked && data.usagePercent !== undefined) || (!isUnlocked && !isComingSoon && !!data.freeTier)
    const usagePercent = isUnlocked ? (data.usagePercent ?? 0) : 0
    const usageBarColor = usagePercent > 0.85 ? 'var(--danger)' : data.color

    return (
        <div
            className={clsx('ProductExplorerNode', `ProductExplorerNode--${data.status}`, {
                'ProductExplorerNode--core': isCore,
                'ProductExplorerNode--selected': selected,
            })}
            onClick={!isCore ? onClick : undefined}
        >
            <div
                className="ProductExplorerNode__icon"
                // eslint-disable-next-line react/forbid-dom-props
                style={iconStyle(data)}
            >
                <IconComponent className="w-4 h-4" />
            </div>
            <div className="ProductExplorerNode__text">
                <div className="ProductExplorerNode__label">{data.label}</div>
                {meta && <div className="ProductExplorerNode__meta">{meta}</div>}
                {hasUsageBar && !isCore && (
                    <div className="ProductExplorerNode__usage-bar">
                        {usagePercent > 0 && (
                            <div
                                className="ProductExplorerNode__usage-bar-fill"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    width: `${Math.min(usagePercent * 100, 100)}%`,
                                    background: usageBarColor,
                                }}
                            />
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
