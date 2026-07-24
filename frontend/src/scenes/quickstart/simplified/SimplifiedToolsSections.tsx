import { useValues } from 'kea'

import { IconApps } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { QUICKSTART_PRODUCT_LAYOUT } from '../productLayout'
import { quickstartLogic } from '../quickstartLogic'
import { HeaderStat } from '../shared/HeaderStat'
import { SectionHeader } from '../shared/SectionHeader'
import { SimplifiedToolCard } from './SimplifiedToolCard'
import { SimplifiedToolRow } from './SimplifiedToolRow'

/** The tool grids for the simplified arm: one click per tool, no per-card controls. */
export function SimplifiedToolsSections(): JSX.Element {
    const { featuredProducts, additionalProducts, activeProductCount, totalProductCount, activationDataLoading } =
        useValues(quickstartLogic)

    return (
        <>
            <section>
                <div className="flex flex-wrap items-start justify-between gap-x-8">
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
            </section>
            {additionalProducts.length > 0 && (
                <section>
                    <SectionHeader
                        title={QUICKSTART_PRODUCT_LAYOUT.additional.title}
                        subtitle={QUICKSTART_PRODUCT_LAYOUT.additional.description}
                    />
                    <div className="grid grid-cols-1 @3xl/main-content:grid-cols-2 gap-3">
                        {additionalProducts.map((product) => (
                            <SimplifiedToolRow key={product.key} product={product} />
                        ))}
                    </div>
                </section>
            )}
        </>
    )
}
