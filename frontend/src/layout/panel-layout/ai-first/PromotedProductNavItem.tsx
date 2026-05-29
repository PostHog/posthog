import { useActions, useValues } from 'kea'

import { IconRocket } from '@posthog/icons'

import { SidePanelTab } from '~/types'

import { NavLink } from './NavLink'
import {
    isAiChatTarget,
    labelForPromotedProductKey,
    promotedProductLogic,
    promotedProductTargetToUrl,
} from './promotedProductLogic'

interface PromotedProductNavItemProps {
    isCollapsed: boolean
}

export function PromotedProductNavItem({ isCollapsed }: PromotedProductNavItemProps): JSX.Element | null {
    const { shouldRenderEntry, shouldRenderCog, effectiveTarget } = useValues(promotedProductLogic)
    const { trackPromotedProductClick, showConfigureModal, openSidePanel } = useActions(promotedProductLogic)

    if (!shouldRenderEntry || !effectiveTarget) {
        return null
    }

    const isAiChat = isAiChatTarget(effectiveTarget)
    // AI chat opens the Max side panel instead of navigating; '#' keeps the anchor inert
    // and the onClick below preventDefault-s the no-op hash navigation.
    const to = isAiChat ? '#' : (promotedProductTargetToUrl(effectiveTarget) ?? '#')

    const label =
        effectiveTarget.kind === 'product'
            ? labelForPromotedProductKey(effectiveTarget.value)
            : effectiveTarget.kind === 'ai_chat'
              ? 'AI chat'
              : effectiveTarget.value

    return (
        <NavLink
            to={to}
            label={label}
            icon={<IconRocket />}
            isCollapsed={isCollapsed}
            data-attr="nav-item-promoted-product"
            onClick={(e) => {
                if (isAiChat) {
                    e.preventDefault()
                    openSidePanel(SidePanelTab.Max)
                }
                trackPromotedProductClick()
            }}
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
