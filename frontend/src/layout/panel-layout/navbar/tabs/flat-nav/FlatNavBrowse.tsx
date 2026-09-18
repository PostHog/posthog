import './FlatNavBrowse.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock, IconHome, IconNotification } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { ActivityTab } from '~/types'

import { NavLink } from '../../NavLink'
import { FlatNavPanelButtons } from './FlatNavPanelButtons'
import { FlatNavProducts } from './FlatNavProducts'
import { FlatNavRecents } from './FlatNavRecents'

export function FlatNavBrowse(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { sidebarDensity, isSidebarSectionShown, isSidebarItemShown, uiCustomizationEnabled } =
        useValues(uiCustomizationLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const { reportNavItemClicked } = useActions(eventUsageLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    return (
        <div className="FlatNavBrowse flex flex-col flex-1 overflow-hidden" data-nav-density={sidebarDensity}>
            <ScrollableShadows
                className="flex-1"
                innerClassName="overflow-y-auto overflow-x-hidden pl-2 pr-0.5 pt-1 focus-visible:outline-accent -outline-offset-2"
                direction="vertical"
                styledScrollbars
            >
                <div className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}>
                    {isSidebarItemShown('home') && (
                        <NavLink
                            to={urls.projectRoot()}
                            label="Home"
                            icon={<IconHome />}
                            isCollapsed={isLayoutNavCollapsed}
                            data-attr="nav-item-home"
                            onClick={() => reportNavItemClicked('home', 'primary')}
                            sideAction={{
                                onClick: () =>
                                    uiCustomizationEnabled
                                        ? router.actions.push(urls.settings('user-navigation', 'homepage'))
                                        : showConfigureHomeModal(),
                                tooltip: 'Configure home',
                                'data-attr': 'nav-configure-home',
                            }}
                        />
                    )}

                    {isProductAutonomyEnabled && isSidebarItemShown('inbox') && (
                        <NavLink
                            to={urls.inbox()}
                            label="Self-driving"
                            icon={<IconNotification />}
                            isCollapsed={isLayoutNavCollapsed}
                            data-attr="nav-item-inbox"
                            tag="beta"
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

                    <FlatNavPanelButtons />
                </div>

                {!isLayoutNavCollapsed && isSidebarSectionShown('recents') && <FlatNavRecents />}
                {!isLayoutNavCollapsed && isSidebarSectionShown('my_tools') && <FlatNavProducts />}
            </ScrollableShadows>
        </div>
    )
}
