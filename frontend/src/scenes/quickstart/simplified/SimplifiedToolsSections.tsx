import { useValues } from 'kea'
import { useState } from 'react'

import { IconApps } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { QUICKSTART_PRODUCT_LAYOUT } from '../productLayout'
import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { HeaderStat } from '../shared/HeaderStat'
import { SectionHeader } from '../shared/SectionHeader'
import { ExploreToolsModal } from './ExploreToolsModal'
import { SimplifiedToolCard } from './SimplifiedToolCard'

/** The tool grid for the simplified arm: one click per tool, no per-card controls.
 * Non-featured tools stay behind an Explore more tools dialog. */
export function SimplifiedToolsSections(): JSX.Element {
    const { featuredProducts, additionalProducts, activeProductCount, totalProductCount, activationDataLoading } =
        useValues(quickstartLogic)
    const [exploreToolsOpen, setExploreToolsOpen] = useState(false)

    return (
        <section>
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-2">
                <SectionHeader
                    title={QUICKSTART_PRODUCT_LAYOUT.featured.title}
                    subtitle={QUICKSTART_PRODUCT_LAYOUT.featured.description}
                />
                <HeaderStat icon={<IconApps />}>
                    {activeProductCount} of {totalProductCount} live
                    {activationDataLoading && <Spinner textColored />}
                </HeaderStat>
            </div>
            {featuredProducts.length > 0 ? (
                <div className="grid grid-cols-1 @2xl/main-content:grid-cols-2 @5xl/main-content:grid-cols-3 gap-4">
                    {featuredProducts.map((product) => (
                        <SimplifiedToolCard key={product.key} product={product} />
                    ))}
                </div>
            ) : (
                <div className="rounded border border-dashed p-6 text-center text-secondary">
                    Add a product from Explore more tools to keep its setup and activity here.
                </div>
            )}
            {additionalProducts.length > 0 && (
                <div className="mt-4">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => {
                            captureQuickstartAction('open_explore_tools')
                            setExploreToolsOpen(true)
                        }}
                        data-attr="quickstart-explore-tools"
                    >
                        {QUICKSTART_PRODUCT_LAYOUT.additional.title}
                    </LemonButton>
                </div>
            )}
            <ExploreToolsModal isOpen={exploreToolsOpen} onClose={() => setExploreToolsOpen(false)} />
        </section>
    )
}
