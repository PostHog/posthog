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
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import { productExplorerLogic } from './productExplorerLogic'

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

export function ProductDetailPanel(): JSX.Element {
    const { selectedNode, unlockedCount, totalProducts } = useValues(productExplorerLogic)

    if (!selectedNode) {
        return (
            <div className="ProductExplorer__detail-empty">
                <div className="ProductExplorer__detail-empty-content">
                    <div className="text-4xl font-bold">{unlockedCount}/{totalProducts}</div>
                    <div className="text-sm text-secondary mt-1">products unlocked</div>
                    <p className="text-sm text-secondary mt-4">
                        Click a product to see details, usage, and how to get started.
                    </p>
                </div>
            </div>
        )
    }

    const IconComponent = ICON_MAP[selectedNode.iconName] || IconBolt
    const isUnlocked = selectedNode.status === 'unlocked'
    const isComingSoon = selectedNode.status === 'coming_soon'

    return (
        <div className="ProductExplorer__detail-panel">
            <div className="ProductExplorer__detail-header">
                <div className="ProductExplorer__detail-icon-row">
                    <div
                        className="ProductExplorer__detail-icon"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            background: isUnlocked ? selectedNode.color : `color-mix(in srgb, ${selectedNode.color} 18%, transparent)`,
                            color: isUnlocked ? 'white' : selectedNode.color,
                        }}
                    >
                        <IconComponent className="w-6 h-6" />
                    </div>
                </div>

                <div>
                    <div className="ProductExplorer__detail-title">{selectedNode.label}</div>
                    <div className="flex items-center gap-2 mt-1">
                        {isUnlocked && (
                            <LemonTag size="small" type="success">
                                Active
                            </LemonTag>
                        )}
                        {isComingSoon && (
                            <LemonTag size="small" type="completion">
                                Coming soon
                            </LemonTag>
                        )}
                        {!isUnlocked && !isComingSoon && (
                            <LemonTag size="small" type="highlight">
                                Available
                            </LemonTag>
                        )}
                    </div>
                </div>
            </div>

            <div className="ProductExplorer__detail-body">
                <div className="ProductExplorer__detail-description">{selectedNode.description}</div>

                {isUnlocked && selectedNode.usagePercent !== undefined && (
                    <div className="ProductExplorer__detail-usage">
                        <div className="ProductExplorer__detail-usage__header">
                            <span>Usage this period</span>
                            <span className="font-semibold">{selectedNode.usageLabel}</span>
                        </div>
                        <div className="ProductExplorer__detail-usage__bar">
                            <div
                                className="ProductExplorer__detail-usage__bar-fill"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    width: `${Math.min(selectedNode.usagePercent * 100, 100)}%`,
                                    background:
                                        selectedNode.usagePercent > 0.85
                                            ? 'var(--danger)'
                                            : selectedNode.color,
                                }}
                            />
                        </div>
                    </div>
                )}

                {!isUnlocked && !isComingSoon && selectedNode.freeTier && (
                    <div className="ProductExplorer__detail-free-tier">
                        <div className="ProductExplorer__detail-free-tier__amount">
                            {selectedNode.freeTier}
                        </div>
                        <div className="text-xs text-secondary">included free every month</div>
                    </div>
                )}

                {!isComingSoon && (
                    <LemonButton
                        type={isUnlocked ? 'secondary' : 'primary'}
                        fullWidth
                        center
                        size="large"
                    >
                        {isUnlocked ? 'Go to product' : 'Start exploring'}
                    </LemonButton>
                )}

                {isComingSoon && (
                    <div className="text-sm text-secondary">
                        This product is currently in development. Check back soon!
                    </div>
                )}
            </div>
        </div>
    )
}
