import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconEllipsis, IconX } from '@posthog/icons'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'

interface PanelLayoutPanelProps {
    searchPlaceholder?: string
    panelActionsNewSceneLayout?: (ButtonPrimitiveProps | null | undefined)[]
    children: React.ReactNode
    filterDropdown?: React.ReactNode
    searchField?: React.ReactNode
    sortDropdown?: React.ReactNode
}

const panelLayoutPanelVariants = cva({
    base: 'w-full flex flex-col max-h-screen min-h-screen absolute border-r border-primary transition-[width] duration-100 prefers-reduced-motion:transition-none',
    variants: {
        isLayoutNavCollapsed: {
            true: '',
            false: '',
        },
        isMobileLayout: {
            true: 'absolute top-0 left-[var(--panel-layout-mobile-offset)] bottom-0 z-[var(--z-layout-panel)]',
            false: '',
        },
        panelWillHide: {
            true: 'opacity-50',
            false: '',
        },
    },
    compoundVariants: [
        {
            isMobileLayout: false,
            className: 'w-full',
        },
        {
            isMobileLayout: true,
            className: 'w-[calc(100vw-var(--panel-layout-mobile-offset)-20px)]',
        },
    ],
})

export function PanelLayoutPanel({
    searchField,
    panelActionsNewSceneLayout,
    children,
    filterDropdown,
    sortDropdown,
}: PanelLayoutPanelProps): JSX.Element {
    const { setPanelWidth, setPanelIsResizing } = useActions(panelLayoutLogic)
    const { isLayoutNavCollapsed, panelWidth: computedPanelWidth, panelWillHide } = useValues(panelLayoutLogic)
    const { closePanel } = useActions(panelLayoutLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)

    // Filter to only include items that have actual properties (not empty objects from spread conditions)
    const validPanelActions = panelActionsNewSceneLayout?.filter(
        (action): action is ButtonPrimitiveProps => !!action && !!action['data-attr']
    )

    const panelContents = (
        <nav
            className={cn(
                panelLayoutPanelVariants({
                    isLayoutNavCollapsed,
                    isMobileLayout,
                    panelWillHide,
                })
            )}
            ref={containerRef}
        >
            <div
                className={cn(
                    'z-main-nav flex flex-1 flex-col justify-between overflow-y-auto bg-surface-secondary group/colorful-product-icons colorful-product-icons-true',
                    'bg-surface-tertiary'
                )}
            >
                {searchField || filterDropdown || sortDropdown ? (
                    <>
                        <div className="flex gap-1 p-1 items-center justify-between">
                            {searchField ?? null}

                            <div className="flex gap-px">
                                {filterDropdown || sortDropdown ? (
                                    <div className="flex gap-px">
                                        {filterDropdown ?? null}
                                        {sortDropdown ?? null}
                                    </div>
                                ) : null}

                                {validPanelActions && validPanelActions.length > 0 && (
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <ButtonPrimitive iconOnly>
                                                <IconEllipsis className="text-tertiary size-3" />
                                            </ButtonPrimitive>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent side="bottom" align="start">
                                            <DropdownMenuGroup>
                                                {validPanelActions.map((action) => (
                                                    <DropdownMenuItem key={action['data-attr']} asChild>
                                                        <ButtonPrimitive menuItem {...action} size="base">
                                                            {action.children}
                                                        </ButtonPrimitive>
                                                    </DropdownMenuItem>
                                                ))}
                                            </DropdownMenuGroup>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                )}

                                <ButtonPrimitive
                                    onClick={() => {
                                        closePanel()
                                    }}
                                    tooltip="Close panel"
                                    iconOnly
                                    data-attr="tree-panel-close-panel-button"
                                    size="sm"
                                >
                                    <IconX className="text-tertiary size-3" />
                                </ButtonPrimitive>
                            </div>
                        </div>
                    </>
                ) : null}

                {children}
            </div>
        </nav>
    )

    return (
        <ResizableElement
            className="absolute left-full h-full"
            key="panel-layout-panel"
            defaultWidth={computedPanelWidth}
            onResize={(width) => {
                setPanelWidth(width)
            }}
            aria-label="Resize handle for panel layout panel"
            borderPosition="right"
            onResizeStart={() => setPanelIsResizing(true)}
            onResizeEnd={() => setPanelIsResizing(false)}
            data-attr="tree-panel-resizer"
        >
            {panelContents}
        </ResizableElement>
    )
}
