import { useActions } from 'kea'

import { IconPin } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { getProductIcon } from 'scenes/onboarding/shared/utils'

import { QuickstartProduct, quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { PRODUCT_SDK_SETUP } from '../shared/productSdkSetup'

/** An explore-more tool as a plain row: name and description, whole row opens the
 * tool. No status badge or per-state button, so scanning the list is one decision. */
export function SimplifiedToolRow({ product }: { product: QuickstartProduct }): JSX.Element {
    const { setProductFeatured, openToolSetupModal } = useActions(quickstartLogic)
    const needsSetup = product.status.level === 'needs_setup'
    const opensSetupModal = needsSetup && !!PRODUCT_SDK_SETUP[product.key]

    return (
        <LemonCard hoverEffect className="relative p-0 rounded-lg min-w-0">
            <Link
                to={opensSetupModal ? undefined : needsSetup ? product.setupUrl : product.url}
                onClick={() => {
                    if (needsSetup) {
                        captureQuickstartAction('set_up_product', product.key)
                        if (opensSetupModal) {
                            openToolSetupModal(product.key)
                        }
                    } else {
                        captureQuickstartAction('open_product', product.key)
                    }
                }}
                className="flex items-center gap-3 p-3 pr-12 text-primary hover:text-primary"
                data-attr={`quickstart-tool-${product.key}`}
            >
                <span className="text-xl leading-none shrink-0">
                    {getProductIcon(product.icon, { iconColor: product.iconColor })}
                </span>
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-sm mb-0 truncate">{product.name}</h3>
                    <p className="text-secondary text-xs mb-0 truncate">{product.description}</p>
                </div>
            </Link>
            <div className="absolute top-1/2 -translate-y-1/2 right-2">
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
