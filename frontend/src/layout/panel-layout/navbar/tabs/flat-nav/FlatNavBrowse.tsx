import './FlatNavBrowse.scss'

import { useValues } from 'kea'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'

import { NavPrimaryLinks } from '../NavPrimaryLinks'
import { FlatNavPanelButtons } from './FlatNavPanelButtons'
import { FlatNavProducts } from './FlatNavProducts'
import { FlatNavRecents } from './FlatNavRecents'

export function FlatNavBrowse(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { sidebarDensity, isSidebarSectionShown } = useValues(uiCustomizationLogic)

    return (
        <div className="FlatNavBrowse flex flex-col flex-1 overflow-hidden" data-nav-density={sidebarDensity}>
            <ScrollableShadows
                className="flex-1"
                innerClassName="overflow-y-auto overflow-x-hidden pl-2 pr-0.5 pt-1 focus-visible:outline-accent -outline-offset-2"
                direction="vertical"
                styledScrollbars
            >
                <div className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}>
                    <NavPrimaryLinks />

                    <FlatNavPanelButtons />
                </div>

                {!isLayoutNavCollapsed && isSidebarSectionShown('recents') && <FlatNavRecents />}
                {!isLayoutNavCollapsed && isSidebarSectionShown('my_tools') && <FlatNavProducts />}
            </ScrollableShadows>
        </div>
    )
}
