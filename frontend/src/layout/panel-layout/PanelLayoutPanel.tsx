import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconEllipsis, IconPin, IconX } from '@posthog/icons'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { PROJECT_TREE_KEY } from './ProjectTree/ProjectTree'
import { projectTreeLogic } from './ProjectTree/projectTreeLogic'

interface PanelLayoutPanelProps {
    searchPlaceholder?: string
    panelActionsNewSceneLayout?: (ButtonPrimitiveProps | null | undefined)[]
    children: React.ReactNode
    filterDropdown?: React.ReactNode
    searchField?: React.ReactNode
    sortDropdown?: React.ReactNode
}

const panelLayoutPanelVariants = cva({
    base: 'w-full flex flex-col max-h-screen min-h-screen relative border-r border-primary transition-[width] duration-100 prefers-reduced-motion:transition-none',
    variants: {
        isLayoutPanelPinned: {
            true: 'relative',
            false: 'absolute',
        },
        projectTreeMode: {
            tree: '',
            table: 'absolute top-0 left-0 bottom-0',
        },
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
            projectTreeMode: 'tree',
            isMobileLayout: false,
            className: 'w-[var(--project-panel-width)]',
        },
        {
            isMobileLayout: true,
            className: 'w-[calc(100vw-var(--panel-layout-mobile-offset)-20px)]',
        },
        {
            projectTreeMode: 'table',
            isLayoutNavCollapsed: true,
            isMobileLayout: false,
            className:
                'left-[var(--project-navbar-width-collapsed)] w-[calc(100vw-var(--project-navbar-width-collapsed)-(var(--side-panel-bar-width)*2))]',
        },
        {
            projectTreeMode: 'table',
            isLayoutNavCollapsed: false,
            isMobileLayout: false,
            className:
                'left-[var(--project-navbar-width)] w-[calc(100vw-var(--project-navbar-width)-(var(--side-panel-bar-width)*2))]',
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
    const { toggleLayoutPanelPinned, setPanelWidth, setPanelIsResizing } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelPinned,
        isLayoutNavCollapsed,
        panelWidth: computedPanelWidth,
        panelWillHide,
    } = useValues(panelLayoutLogic)
    const { closePanel } = useActions(panelLayoutLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { projectTreeMode } = useValues(projectTreeLogic({ key: PROJECT_TREE_KEY }))

    const panelContents = (
        <nav
            className={cn(
                panelLayoutPanelVariants({
                    projectTreeMode: projectTreeMode,
                    isLayoutNavCollapsed,
                    isMobileLayout,
                    panelWillHide,
                    isLayoutPanelPinned,
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

                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <ButtonPrimitive iconOnly>
                                            <IconEllipsis className="text-tertiary size-3" />
                                        </ButtonPrimitive>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent side="bottom" align="start">
                                        <DropdownMenuItem asChild>
                                            <ButtonPrimitive
                                                menuItem
                                                active={isLayoutPanelPinned}
                                                onClick={() => toggleLayoutPanelPinned(!isLayoutPanelPinned)}
                                            >
                                                <IconPin className="text-tertiary size-3" />{' '}
                                                {isLayoutPanelPinned ? 'Unpin panel' : 'Pin panel'}
                                            </ButtonPrimitive>
                                        </DropdownMenuItem>
                                        {panelActionsNewSceneLayout?.map(
                                            (action) =>
                                                action &&
                                                action['data-attr'] && (
                                                    <DropdownMenuItem key={action['data-attr']} asChild>
                                                        <ButtonPrimitive menuItem {...action} size="base">
                                                            {action.children}
                                                        </ButtonPrimitive>
                                                    </DropdownMenuItem>
                                                )
                                        )}
                                    </DropdownMenuContent>
                                </DropdownMenu>

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

    if (projectTreeMode === 'table') {
        return panelContents
    }

    return (
        <ResizableElement
            className={cn({
                relative: isLayoutPanelPinned,
                'absolute left-full h-full': !isLayoutPanelPinned,
            })}
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
