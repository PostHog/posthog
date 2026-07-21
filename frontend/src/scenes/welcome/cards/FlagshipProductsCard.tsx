import { useActions } from 'kea'

import { ProductHogHero } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { getProductPushDisplay } from 'lib/components/NavPanelAdvertisement/navPanelProductPushDisplay'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { brandingForProduct } from '../productBranding'
import { welcomeDialogLogic } from '../welcomeDialogLogic'

// The products we want every new account exploring. Both keys resolve in PRODUCT_BRANDING (label +
// docs) and PRODUCT_PUSH_DISPLAY (hog illustration + brand accent + tagline), so the showcase reuses
// the same hog+text visual as the nav advertisement.
const FLAGSHIP_PRODUCT_KEYS = [
    'product_analytics',
    'web_analytics',
    'session_replay',
    'error_tracking',
    'llm_analytics',
] as const

export function FlagshipProductsCard(): JSX.Element {
    const { trackCardClick } = useActions(welcomeDialogLogic)

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <h2 className="text-lg font-semibold mb-1">What you get with PostHog</h2>
            <p className="text-xs text-muted mb-3 m-0">
                One platform, one set of events. Click any product to see how it works.
            </p>
            <div className="grid grid-cols-2 gap-2">
                {FLAGSHIP_PRODUCT_KEYS.map((productKey) => {
                    const display = getProductPushDisplay(productKey)
                    const meta = brandingForProduct(productKey)
                    return (
                        <Link
                            key={productKey}
                            to={meta.docsHref}
                            target="_blank"
                            subtle
                            onClick={() => trackCardClick('products', meta.docsHref)}
                            className="overflow-hidden rounded border bg-surface-primary text-xs shadow-sm transition-shadow hover:shadow-md"
                            data-attr={`welcome-flagship-${productKey}`}
                        >
                            <ProductHogHero hero={display} title={meta.label} text={display.tagline} />
                        </Link>
                    )
                })}
            </div>
        </LemonCard>
    )
}
