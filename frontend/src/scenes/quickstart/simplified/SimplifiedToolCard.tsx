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
 * guide when it needs an install. Opt-in tools (cta enable/open) go to the product,
 * which carries its own enable flow. */
export function SimplifiedToolCard({ product }: { product: QuickstartProduct }): JSX.Element {
    const { setProductFeatured, openToolSetupModal } = useActions(quickstartLogic)
    const needsInstall =
        product.status.level === 'needs_setup' && (product.status.cta === 'install' || product.status.cta === 'setup')
    const opensSetupModal = needsInstall && !!PRODUCT_SDK_SETUP[product.key]

    return (
        <LemonCard hoverEffect className="relative p-0 rounded-lg border-transparent shadow-sm">
            <Link
                to={opensSetupModal ? undefined : needsInstall ? product.setupUrl : product.url}
                onClick={() => {
                    if (needsInstall) {
                        captureQuickstartAction('set_up_product', product.key, { source: 'featured_card' })
                        if (opensSetupModal) {
                            openToolSetupModal(product.key)
                        }
                    } else {
                        captureQuickstartAction('open_product', product.key, { source: 'featured_card' })
                    }
                }}
                className="flex flex-col gap-2 p-4 h-full text-primary hover:text-primary"
                data-attr={`quickstart-tool-${product.key}`}
            >
                <span className="text-2xl leading-none">
                    {getProductIcon(product.icon, { iconColor: product.iconColor })}
                </span>
                {/* Spans, not h3/p: with to=undefined the Link renders a <button>, which only
                    allows phrasing content */}
                <span className="block font-semibold text-base">{product.name}</span>
                <span className="block text-secondary text-sm text-left flex-1">{product.description}</span>
                <ToolStatusLine status={product.status} />
            </Link>
            <div className="absolute top-2 right-2">
                <LemonButton
                    size="xsmall"
                    icon={<IconPinFilled />}
                    tooltip="Remove from Your tools"
                    aria-label={`Remove ${product.name} from Your tools`}
                    onClick={() => {
                        captureQuickstartAction('unfeature_product', product.key)
                        setProductFeatured(product.key, false)
                    }}
                    data-attr={`quickstart-unfeature-${product.key}`}
                />
            </div>
        </LemonCard>
    )
}
