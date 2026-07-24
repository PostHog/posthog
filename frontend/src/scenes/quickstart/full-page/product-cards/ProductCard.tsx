import { useActions } from 'kea'

import { IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { getProductIcon } from 'scenes/onboarding/shared/utils'
import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

import { QuickstartProduct, quickstartLogic } from '../../quickstartLogic'
import { isQuickstartProductInstalling } from '../../shared/QuickstartWizardProgress'
import { ProductActions } from './ProductActions'
import { ToolActivitySummary } from './ToolActivitySummary'
import { ToolStatusPanel } from './ToolStatusPanel'

export function ProductCard({
    product,
    installationProgress,
}: {
    product: QuickstartProduct
    installationProgress?: InstallationProgress
}): JSX.Element {
    const { setProductFeatured } = useActions(quickstartLogic)
    const installationInProgress = isQuickstartProductInstalling(product.key, installationProgress)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 rounded-lg border-transparent shadow-sm">
            <div className="flex items-start justify-between gap-3">
                <div className="flex flex-col gap-2 min-w-0">
                    <span className="text-2xl leading-none">
                        {getProductIcon(product.icon, { iconColor: product.iconColor })}
                    </span>
                    <h3 className="font-semibold text-base mb-0">{product.name}</h3>
                </div>
                <LemonButton
                    size="xsmall"
                    icon={<IconPinFilled />}
                    tooltip="Remove from Your tools"
                    aria-label={`Remove ${product.name} from Your tools`}
                    onClick={() => setProductFeatured(product.key, false)}
                    data-attr={`quickstart-unfeature-${product.key}`}
                />
            </div>
            <div className="flex flex-col gap-1">
                <p className="text-secondary text-sm leading-relaxed mb-0">{product.description}</p>
                <ToolActivitySummary
                    product={product}
                    status={product.status}
                    installationInProgress={installationInProgress}
                />
            </div>
            <ToolStatusPanel
                status={product.status}
                productKey={product.key}
                installationProgress={installationProgress}
            />
            <ProductActions product={product} installationProgress={installationProgress} />
        </LemonCard>
    )
}
