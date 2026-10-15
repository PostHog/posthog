import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock, IconGear, IconHome, IconNotification } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { NavLink } from '~/layout/panel-layout/navbar/NavLink'
import { NavLinkSideActionButton } from '~/layout/panel-layout/navbar/NavLinkSideActionButton'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { ActivityTab } from '~/types'

export function NavPrimaryLinks(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { isSidebarItemShown, uiCustomizationEnabled } = useValues(uiCustomizationLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const { reportNavItemClicked } = useActions(eventUsageLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    return (
        <>
            {isSidebarItemShown('home') && (
                <NavLink
                    to={urls.projectRoot()}
                    label="Home"
                    icon={<IconHome />}
                    isCollapsed={isLayoutNavCollapsed}
                    data-attr="nav-item-home"
                    onClick={() => reportNavItemClicked('home', 'primary')}
                    sideAction={
                        <NavLinkSideActionButton
                            icon={<IconGear />}
                            tooltip="Configure home"
                            data-attr="nav-configure-home"
                            onClick={(e) => {
                                e.stopPropagation()
                                if (uiCustomizationEnabled) {
                                    router.actions.push(urls.settings('user-navigation', 'homepage'))
                                } else {
                                    showConfigureHomeModal()
                                }
                            }}
                        />
                    }
                />
            )}

            {isProductAutonomyEnabled && isSidebarItemShown('inbox') && (
                <NavLink
                    to={urls.inbox()}
                    label="Self-driving"
                    icon={<IconNotification />}
                    isCollapsed={isLayoutNavCollapsed}
                    data-attr="nav-item-inbox"
                    onClick={() => reportNavItemClicked('inbox', 'primary')}
                />
            )}

            <NavLink
                to={urls.activity(ActivityTab.ExploreEvents)}
                label="Activity"
                icon={<IconClock />}
                isCollapsed={isLayoutNavCollapsed}
                data-attr="nav-item-activity"
                onClick={() => reportNavItemClicked('activity', 'primary')}
            />
        </>
    )
}
