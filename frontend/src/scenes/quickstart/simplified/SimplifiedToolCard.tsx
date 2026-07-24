import { useActions } from 'kea'

import { IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { getProductIcon } from 'scenes/onboarding/shared/utils'

import { QuickstartProduct, quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { PRODUCT_SDK_SETUP } from '../shared/productSdkSetup'
import { ToolStatusLine } from './ToolStatusLine'

/** A featured tool as one decision: the whole card opens the tool, or its setup
 * guide when it isn't collecting data yet. */
export function SimplifiedToolCard({ product }: { product: QuickstartProduct }): JSX.Element {
    const { setProductFeatured, openToolSetupModal } = useActions(quickstartLogic)
    const needsSetup = product.status.level === 'needs_setup'
    const hasSetupGuide = !!PRODUCT_SDK_SETUP[product.key]
    const opensSetupModal = needsSetup && hasSetupGuide

    return (
        <LemonCard hoverEffect className="relative p-0 rounded-lg border-transparent shadow-sm">
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
                className="flex flex-col gap-2 p-4 text-primary hover:text-primary"
                data-attr={`quickstart-tool-${product.key}`}
            >
                <span className="text-2xl leading-none">
                    {getProductIcon(product.icon, { iconColor: product.iconColor })}
                </span>
                <h3 className="font-semibold text-base mb-0">{product.name}</h3>
                <p className="text-secondary text-sm mb-0">{product.description}</p>
                <ToolStatusLine status={product.status} />
            </Link>
            <div className="absolute top-2 right-2">
                <LemonButton
                    size="xsmall"
                    icon={<IconPinFilled />}
                    tooltip="Remove from Your tools"
                    aria-label={`Remove ${product.name} from Your tools`}
                    onClick={() => setProductFeatured(product.key, false)}
                    data-attr={`quickstart-unfeature-${product.key}`}
                />
            </div>
        </LemonCard>
    )
}
