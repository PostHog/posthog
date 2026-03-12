import { useActions, useValues } from 'kea'

import {
    IconApps,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconHome,
    IconNotification,
    IconStar,
} from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { ActivityTab } from '~/types'

import { SectionTrigger } from '../Nav'

const panelTriggerItems: {
    identifier: PanelLayoutNavIdentifier
    label: string
    icon: React.ReactNode
}[] = [
    {
        identifier: 'DataAndPeople',
        label: 'Data',
        icon: <IconDatabase />,
    },
    {
        identifier: 'Project',
        label: 'Files',
        icon: <IconFolderOpen className="stroke-[1.2]" />,
    },
    {
        identifier: 'Products',
        label: 'Apps',
        icon: <IconApps />,
    },
    {
        identifier: 'Shortcuts',
        label: 'Starred',
        icon: <IconStar />,
    },
]

export function NavTabBrowse(): JSX.Element {
    const { showLayoutPanel, setActivePanelIdentifier, clearActivePanelIdentifier, toggleNavSection } =
        useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        isLayoutNavCollapsed,
        expandedNavSections,
        activePanelIdentifier,
        activePanelIdentifierFromUrlAiFirst,
    } = useValues(panelLayoutLogic)
    const { firstTabIsActive } = useValues(sceneLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        if (activePanelIdentifier !== item) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else if (activePanelIdentifier === item) {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

    return (
        <ScrollableShadows
            className={cn('flex-1', {
                'rounded-tr': !isLayoutPanelVisible && !firstTabIsActive,
            })}
            innerClassName="overflow-y-auto overflow-x-hidden px-1"
            direction="vertical"
            styledScrollbars
        >
            <Collapsible
                open={expandedNavSections.project ?? true}
                onOpenChange={() => toggleNavSection('project')}
                className="mt-1"
            >
                <Collapsible.Trigger
                    icon={!isLayoutNavCollapsed ? <IconFolder /> : undefined}
                    className={cn(isLayoutNavCollapsed && 'px-px')}
                    labelClassName={cn(isLayoutNavCollapsed && 'text-[7px] m-0 w-full text-center')}
                    hideChevron={isLayoutNavCollapsed}
                >
                    Project
                </Collapsible.Trigger>
                <Collapsible.Panel className={cn('pl-2', isLayoutNavCollapsed && 'items-center')}>
                    <NavLink
                        to={urls.projectRoot()}
                        label="Home"
                        icon={<IconHome />}
                        isCollapsed={isLayoutNavCollapsed}
                    />

                    {isProductAutonomyEnabled && (
                        <NavLink
                            to={urls.inbox()}
                            label="Inbox"
                            icon={<IconNotification />}
                            isCollapsed={isLayoutNavCollapsed}
                        />
                    )}

                    <NavLink
                        to={urls.activity(ActivityTab.ExploreEvents)}
                        label="Activity"
                        icon={<IconClock />}
                        isCollapsed={isLayoutNavCollapsed}
                    />

                    <div className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}>
                        {panelTriggerItems.map((item) => {
                            const isActive =
                                activePanelIdentifier === item.identifier ||
                                activePanelIdentifierFromUrlAiFirst === item.identifier
                            const tooltip = isLayoutNavCollapsed
                                ? isLayoutPanelVisible && activePanelIdentifier === item.identifier
                                    ? `Close ${item.label.toLowerCase()}`
                                    : `Open ${item.label.toLowerCase()}`
                                : undefined

                            return (
                                <ButtonPrimitive
                                    key={item.identifier}
                                    active={isActive}
                                    className="group"
                                    menuItem={!isLayoutNavCollapsed}
                                    iconOnly={isLayoutNavCollapsed}
                                    tooltip={tooltip}
                                    tooltipPlacement="right"
                                    onClick={() => handlePanelTriggerClick(item.identifier)}
                                    data-attr={`menu-item-${item.identifier.toLowerCase()}`}
                                >
                                    <span className="size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50">
                                        {item.icon}
                                    </span>
                                    {!isLayoutNavCollapsed && (
                                        <>
                                            <span className="truncate">{item.label}</span>
                                            <span className="ml-auto pr-1">
                                                <IconChevronRight
                                                    className={cn(
                                                        'size-3 text-tertiary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                                        isActive && 'opacity-100'
                                                    )}
                                                />
                                            </span>
                                        </>
                                    )}
                                </ButtonPrimitive>
                            )
                        })}
                    </div>
                </Collapsible.Panel>
            </Collapsible>

            <Collapsible
                open={expandedNavSections.apps ?? false}
                onOpenChange={() => toggleNavSection('apps')}
                className="px-2 mt-2 group/colorful-product-icons colorful-product-icons-true"
            >
                <SectionTrigger
                    icon={<IconApps />}
                    label={isLayoutNavCollapsed ? 'Apps' : 'All apps'}
                    isCollapsed={isLayoutNavCollapsed}
                />
                <Collapsible.Panel
                    className={cn(
                        '-ml-2 pl-2 w-[calc(100%+(var(--spacing)*4))]',
                        isLayoutNavCollapsed ? 'items-center' : ''
                    )}
                >
                    {(expandedNavSections.apps ?? false) && (
                        <ProjectTree
                            root="products://"
                            onlyTree
                            treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'}
                        />
                    )}
                </Collapsible.Panel>
            </Collapsible>
        </ScrollableShadows>
    )
}
