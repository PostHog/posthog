import { useActions, useValues } from 'kea'

import { IconRocket } from '@posthog/icons'

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
        effectiveTarget.kind === 'product' ? labelForPromotedProductKey(effectiveTarget.value) : effectiveTarget.value

    return (
        <NavLink
            to={to}
            label={label}
            icon={<IconRocket />}
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
