import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'

import { getProductIcon } from 'scenes/onboarding/utils'

import { NavLink } from './NavLink'
import { labelForPromotedProductKey, promotedProductLogic, promotedProductTargetToUrl } from './promotedProductLogic'

interface PromotedProductNavItemProps {
    isCollapsed: boolean
}

export function PromotedProductNavItem({ isCollapsed }: PromotedProductNavItemProps): JSX.Element | null {
    const { shouldRenderEntry, shouldRenderCog, effectiveTarget } = useValues(promotedProductLogic)
    const { trackPromotedProductClick, showConfigureModal } = useActions(promotedProductLogic)

    if (!shouldRenderEntry || !effectiveTarget) {
        return null
    }

    const to = promotedProductTargetToUrl(effectiveTarget) ?? '#'

    const label =
        effectiveTarget.kind === 'product'
            ? labelForPromotedProductKey(effectiveTarget.value)
            : (effectiveTarget.label ?? effectiveTarget.value)

    const icon =
        effectiveTarget.kind === 'product' ? (
            getProductIcon(null, { productType: effectiveTarget.value })
        ) : (
            <IconExternal />
        )

    return (
        <NavLink
            to={to}
            label={label}
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
