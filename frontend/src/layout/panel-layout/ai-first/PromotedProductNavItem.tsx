import { useActions, useValues } from 'kea'

import { IconDashboard } from '@posthog/icons'

import { getProductIcon } from 'scenes/onboarding/utils'

import { NavLink } from './NavLink'
import {
    FALLBACK_PRODUCT_KEY,
    labelForPromotedProductKey,
    promotedProductLogic,
    urlForPromotedProductKey,
} from './promotedProductLogic'

interface PromotedProductNavItemProps {
    isCollapsed: boolean
}

export function PromotedProductNavItem({ isCollapsed }: PromotedProductNavItemProps): JSX.Element | null {
    const { shouldRenderEntry, shouldRenderCog, effectiveProductKey } = useValues(promotedProductLogic)
    const { trackPromotedProductClick, showConfigureModal } = useActions(promotedProductLogic)

    if (!shouldRenderEntry || !effectiveProductKey) {
        return null
    }

    const icon =
        effectiveProductKey === FALLBACK_PRODUCT_KEY ? (
            <IconDashboard />
        ) : (
            getProductIcon(null, { productType: effectiveProductKey })
        )

    return (
        <NavLink
            to={urlForPromotedProductKey(effectiveProductKey) ?? '#'}
            label={labelForPromotedProductKey(effectiveProductKey)}
            icon={icon}
            isCollapsed={isCollapsed}
            data-attr="nav-item-promoted-product"
            onClick={() => trackPromotedProductClick()}
            sideAction={
                shouldRenderCog
                    ? {
                          onClick: () => showConfigureModal(),
                          tooltip: 'Configure promoted product',
                          'data-attr': 'nav-configure-promoted-product',
                      }
                    : undefined
            }
        />
    )
}
