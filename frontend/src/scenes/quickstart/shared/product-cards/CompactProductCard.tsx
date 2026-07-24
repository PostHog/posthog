import { useActions } from 'kea'

import { IconPin } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { getProductIcon } from 'scenes/onboarding/shared/utils'
import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

import { QuickstartProduct, quickstartLogic } from '../../quickstartLogic'
import { isQuickstartProductInstalling } from '../QuickstartWizardProgress'
import { ProductActions } from './ProductActions'

export function CompactProductCard({
    product,
    installationProgress,
}: {
    product: QuickstartProduct
    installationProgress?: InstallationProgress
}): JSX.Element {
    const { setProductFeatured } = useActions(quickstartLogic)
    const installationInProgress = isQuickstartProductInstalling(product.key, installationProgress)
    const statusLabel = installationInProgress
        ? 'Installing'
        : product.status.level === 'live'
          ? 'Live'
          : product.status.level === 'ready'
            ? 'Waiting for data'
            : 'Needs setup'

    return (
        <LemonCard hoverEffect={false} className="flex items-center gap-3 p-3 rounded-lg min-w-0">
            <span className="text-xl leading-none shrink-0">
                {getProductIcon(product.icon, { iconColor: product.iconColor })}
            </span>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <h3 className="font-semibold text-sm mb-0 truncate">{product.name}</h3>
                    <LemonTag
                        size="small"
                        type={
                            installationInProgress
                                ? 'primary'
                                : product.status.level === 'live'
                                  ? 'success'
                                  : product.status.level === 'ready'
                                    ? 'warning'
                                    : 'muted'
                        }
                        className="shrink-0"
                    >
                        {statusLabel}
                    </LemonTag>
                </div>
                <p className="text-secondary text-xs mb-0 truncate">{product.description}</p>
            </div>
            <div className="flex items-center gap-1 shrink-0">
                <ProductActions product={product} compact installationProgress={installationProgress} />
                <LemonButton
                    size="small"
                    icon={<IconPin />}
                    tooltip="Add to Your tools"
                    aria-label={`Add ${product.name} to Your tools`}
                    onClick={() => setProductFeatured(product.key, true)}
                    data-attr={`quickstart-feature-${product.key}`}
                />
            </div>
        </LemonCard>
    )
}
