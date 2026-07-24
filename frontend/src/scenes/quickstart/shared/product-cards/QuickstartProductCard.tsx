import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { QuickstartProduct } from '../../quickstartLogic'
import { QuickstartWizardProgress } from '../QuickstartWizardProgress'
import { CompactProductCard } from './CompactProductCard'
import { ProductCard } from './ProductCard'

export function QuickstartProductCard({
    product,
    compact = false,
}: {
    product: QuickstartProduct
    compact?: boolean
}): JSX.Element {
    const renderCard = (installationProgress?: InstallationProgress): JSX.Element =>
        compact ? (
            <CompactProductCard product={product} installationProgress={installationProgress} />
        ) : (
            <ProductCard product={product} installationProgress={installationProgress} />
        )

    if (product.key !== ProductKey.PRODUCT_ANALYTICS) {
        return renderCard()
    }

    return (
        <QuickstartWizardProgress fallback={renderCard()}>
            {(progress) => renderCard(progress)}
        </QuickstartWizardProgress>
    )
}
