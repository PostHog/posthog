import './ProductExplorer.scss'

import { IconSparkles } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { useCallback } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductDetailPanel } from './ProductDetailPanel'
import { productExplorerLogic } from './productExplorerLogic'
import { ProductExplorerNode, type ProductExplorerNodeData } from './ProductExplorerNode'

export const scene: SceneExport = {
    component: ProductExplorer,
    logic: productExplorerLogic,
}

const CATEGORY_GROUPS = [
    { label: 'Analytics', categories: ['analytics'] },
    { label: 'Observe & understand', categories: ['behavior'] },
    { label: 'Ship & test', categories: ['features'] },
    { label: 'AI & Data', categories: ['ai', 'data'] },
]

export function ProductExplorer(): JSX.Element {
    const { enrichedNodes, selectedNode, unlockedCount, totalProducts, nextRecommendation } =
        useValues(productExplorerLogic)
    const { setSelectedNode } = useActions(productExplorerLogic)

    const onNodeClick = useCallback(
        (node: ProductExplorerNodeData) => {
            if (node.id !== 'events_core') {
                setSelectedNode(node)
            }
        },
        [setSelectedNode]
    )

    const coreNode = enrichedNodes.find((n) => n.id === 'events_core')

    return (
        <div className="ProductExplorer">
            <div className="ProductExplorer__header">
                <div className="ProductExplorer__title">
                    <IconSparkles className="w-5 h-5 text-warning" />
                    Product explorer
                </div>
                <div className="ProductExplorer__stats">
                    <strong>{unlockedCount}</strong>
                    <span>of {totalProducts} unlocked</span>
                </div>
            </div>

            <div className="ProductExplorer__split">
                <div className="ProductExplorer__left">
                    {coreNode && (
                        <div className="ProductExplorer__hero">
                            <ProductExplorerNode data={coreNode} />
                            <p className="ProductExplorer__hero-description">
                                Once events flow in, everything below unlocks.
                            </p>
                        </div>
                    )}

                    {CATEGORY_GROUPS.map((group) => {
                        const nodes = enrichedNodes.filter(
                            (n) => n.id !== 'events_core' && group.categories.includes(n.category)
                        )
                        if (nodes.length === 0) {
                            return null
                        }
                        return (
                            <div key={group.label} className="ProductExplorer__section">
                                <h3 className="ProductExplorer__section-label">{group.label}</h3>
                                <div className="ProductExplorer__section-grid">
                                    {nodes.map((node) => (
                                        <ProductExplorerNode
                                            key={node.id}
                                            data={node}
                                            onClick={() => onNodeClick(node)}
                                            selected={selectedNode?.id === node.id}
                                        />
                                    ))}
                                </div>
                            </div>
                        )
                    })}

                    {nextRecommendation && !selectedNode && (
                        <div className="ProductExplorer__recommendation">
                            <span className="ProductExplorer__recommendation-label">Suggested next</span>
                            <span>
                                <strong>{nextRecommendation.label}</strong> —{' '}
                                {nextRecommendation.shortDescription}.
                                {nextRecommendation.freeTier && (
                                    <> {nextRecommendation.freeTier} free every month.</>
                                )}
                            </span>
                        </div>
                    )}
                </div>

                <div className="ProductExplorer__right">
                    <ProductDetailPanel />
                </div>
            </div>
        </div>
    )
}

export default ProductExplorer
