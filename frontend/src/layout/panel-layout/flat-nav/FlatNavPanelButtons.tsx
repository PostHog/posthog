import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconApps, IconChevronRight, IconDatabase, IconFolderOpen, IconStar } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { PanelIndicatorIcon } from '~/layout/panel-layout/ai-first/Nav'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidebarItemKey, uiCustomizationLogic } from '~/layout/uiCustomizationLogic'

const PANEL_TRIGGER_ITEMS: {
    identifier: PanelLayoutNavIdentifier
    configKey: SidebarItemKey
    label: string
    icon: React.ReactNode
}[] = [
    { identifier: 'DataAndPeople', configKey: 'data', label: 'Data', icon: <IconDatabase /> },
    { identifier: 'Project', configKey: 'files', label: 'Files', icon: <IconFolderOpen className="stroke-[1.2]" /> },
    { identifier: 'Products', configKey: 'tools', label: 'Tools', icon: <IconApps /> },
    { identifier: 'Shortcuts', configKey: 'starred', label: 'Starred', icon: <IconStar /> },
]

export function FlatNavPanelButtons(): JSX.Element {
    const { showLayoutPanel, setActivePanelIdentifier, clearActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed, activePanelIdentifier, activePanelIdentifierFromUrlAiFirst } =
        useValues(panelLayoutLogic)
    const { isSidebarItemShown } = useValues(uiCustomizationLogic)

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        const isOpening = activePanelIdentifier !== item
        posthog.capture('nav panel trigger clicked', { panel: item, is_open: isOpening })
        if (isOpening) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

    return (
        <>
            {PANEL_TRIGGER_ITEMS.filter((item) => isSidebarItemShown(item.configKey)).map((item) => {
                const isActive =
                    activePanelIdentifier === item.identifier || activePanelIdentifierFromUrlAiFirst === item.identifier
                const tooltip = isLayoutNavCollapsed
                    ? isLayoutPanelVisible && activePanelIdentifier === item.identifier
                        ? `Close ${item.label.toLowerCase()}`
                        : `Open ${item.label.toLowerCase()}`
                    : undefined

                return (
                    <ButtonPrimitive
                        key={item.identifier}
                        active={isActive}
                        className="group -outline-offset-2"
                        menuItem={!isLayoutNavCollapsed}
                        iconOnly={isLayoutNavCollapsed}
                        tooltip={tooltip}
                        tooltipPlacement="right"
                        onClick={() => handlePanelTriggerClick(item.identifier)}
                        data-attr={`menu-item-${item.identifier.toLowerCase()}`}
                    >
                        <span
                            className={cn(
                                'relative size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                isActive && 'text-primary opacity-100'
                            )}
                        >
                            {item.icon}
                            <PanelIndicatorIcon />
                        </span>
                        {!isLayoutNavCollapsed && (
                            <>
                                <span
                                    className={cn(
                                        'truncate text-secondary group-hover:text-primary',
                                        isActive && 'text-primary'
                                    )}
                                >
                                    {item.label}
                                </span>
                                <span className="ml-auto pr-1">
                                    <IconChevronRight
                                        className={cn(
                                            'size-3 text-secondary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                            isActive && 'opacity-100'
                                        )}
                                    />
                                </span>
                            </>
                        )}
                    </ButtonPrimitive>
                )
            })}
        </>
    )
}
