import { IconPin, IconPinFilled, IconX } from '@posthog/icons'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { ProjectDropdownMenu } from './ProjectDropdownMenu'
import { PROJECT_TREE_KEY } from './ProjectTree/ProjectTree'
import { projectTreeLogic } from './ProjectTree/projectTreeLogic'

interface PanelLayoutPanelProps {
    searchPlaceholder?: string
    panelActions?: React.ReactNode
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
    panelActions,
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
    const { showLayoutPanel, clearActivePanelIdentifier } = useActions(panelLayoutLogic)
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
            <div className="flex justify-between p-1 gap-px bg-surface-tertiary">
                <ProjectDropdownMenu />

                <div className="flex gap-px items-center justify-end shrink-0">
                    {!isMobileLayout && (
                        <ButtonPrimitive
                            iconOnly
                            onClick={() => toggleLayoutPanelPinned(!isLayoutPanelPinned)}
                            tooltip={isLayoutPanelPinned ? 'Unpin panel' : 'Pin panel'}
                            data-attr={`tree-navbar-${isLayoutPanelPinned ? 'unpin' : 'pin'}-panel-button`}
                            active={isLayoutPanelPinned}
                            size="sm"
                            aria-pressed={isLayoutPanelPinned}
                        >
                            {isLayoutPanelPinned ? (
                                <IconPinFilled className="size-3 text-primary" />
                            ) : (
                                <IconPin className="size-3 text-tertiary" />
                            )}
                        </ButtonPrimitive>
                    )}

                    {panelActions ?? null}

                    <ButtonPrimitive
                        onClick={() => {
                            showLayoutPanel(false)
                            clearActivePanelIdentifier()
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
            <div className="border-b border-primary h-px" />
            <div className="z-main-nav flex flex-1 flex-col justify-between overflow-y-auto bg-surface-secondary group/colorful-product-icons colorful-product-icons-true">
                {searchField || filterDropdown || sortDropdown ? (
                    <>
                        <div className="flex gap-1 p-1 items-center justify-between">
                            {searchField ?? null}

                            {filterDropdown || sortDropdown ? (
                                <div className="flex gap-px">
                                    {filterDropdown ?? null}
                                    {sortDropdown ?? null}
                                </div>
                            ) : null}
                        </div>
                        <div className="border-b border-primary h-px" />
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
