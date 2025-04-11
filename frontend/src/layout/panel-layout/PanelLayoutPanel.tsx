import { IconPin, IconPinFilled, IconSearch, IconX } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { ProjectDropdownMenu } from './ProjectDropdownMenu'

interface PanelLayoutPanelProps {
    searchPlaceholder?: string
    panelActions?: React.ReactNode
    children: React.ReactNode
}

const panelLayoutPanelVariants = cva({
    base: 'flex flex-col max-h-screen min-h-screen relative border-r border-primary transition-[width] duration-100 prefers-reduced-motion:transition-none',
    variants: {
        projectTreeMode: {
            tree: 'w-[var(--project-panel-width)]',
            table: 'absolute top-0 left-0 bottom-0',
        },
        isLayoutNavCollapsed: {
            true: '',
            false: '',
        },
    },
    compoundVariants: [
        {
            projectTreeMode: 'table',
            isLayoutNavCollapsed: true,
            className:
                'left-[var(--project-navbar-width-collapsed)] w-[calc(100vw-var(--project-navbar-width-collapsed)-(var(--side-panel-bar-width)*2))]',
        },
        {
            projectTreeMode: 'table',
            isLayoutNavCollapsed: false,
            className:
                'left-[var(--project-navbar-width)] w-[calc(100vw-var(--project-navbar-width)-(var(--side-panel-bar-width)*2))]',
        },
    ],
})

export function PanelLayoutPanel({ searchPlaceholder, panelActions, children }: PanelLayoutPanelProps): JSX.Element {
    const { clearSearch, setSearchTerm, toggleLayoutPanelPinned } = useActions(panelLayoutLogic)
    const { isLayoutPanelPinned, searchTerm, panelTreeRef, projectTreeMode, isLayoutNavCollapsed } =
        useValues(panelLayoutLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)

    return (
        <>
            <nav
                className={cn(
                    panelLayoutPanelVariants({
                        projectTreeMode: projectTreeMode,
                        isLayoutNavCollapsed,
                    })
                )}
                ref={containerRef}
            >
                <div className="flex justify-between p-1 bg-surface-tertiary">
                    <ProjectDropdownMenu />

                    <div className="flex gap-px items-center justify-end shrink-0">
                        {!isMobileLayout && (
                            <ButtonPrimitive
                                iconOnly
                                onClick={() => toggleLayoutPanelPinned(!isLayoutPanelPinned)}
                                tooltip={isLayoutPanelPinned ? 'Unpin panel' : 'Pin panel'}
                            >
                                {isLayoutPanelPinned ? (
                                    <IconPinFilled className="size-3 text-tertiary" />
                                ) : (
                                    <IconPin className="size-3 text-tertiary" />
                                )}
                            </ButtonPrimitive>
                        )}
                        {panelActions ?? null}
                    </div>
                </div>
                <div className="border-b border-primary h-px" />
                <div className="z-main-nav flex flex-1 flex-col justify-between overflow-y-auto bg-surface-secondary">
                    <div className="flex gap-1 p-1 items-center justify-between">
                        <LemonInput
                            placeholder={searchPlaceholder}
                            className="w-full"
                            prefix={
                                <div className="flex items-center justify-center size-4 ml-[2px] mr-px">
                                    <IconSearch className="size-4" />
                                </div>
                            }
                            autoFocus
                            size="small"
                            value={searchTerm}
                            onChange={(value) => setSearchTerm(value)}
                            suffix={
                                searchTerm ? (
                                    <ButtonPrimitive
                                        size="sm"
                                        iconOnly
                                        onClick={() => clearSearch()}
                                        className="bg-transparent [&_svg]:opacity-50 hover:[&_svg]:opacity-100 focus-visible:[&_svg]:opacity-100 -mr-px"
                                        tooltip="Clear search"
                                    >
                                        <IconX className="size-4" />
                                    </ButtonPrimitive>
                                ) : null
                            }
                            onKeyDown={(e) => {
                                if (e.key === 'ArrowDown') {
                                    e.preventDefault() // Prevent scrolling
                                    const visibleItems = panelTreeRef?.current?.getVisibleItems()
                                    if (visibleItems && visibleItems.length > 0) {
                                        e.currentTarget.blur() // Remove focus from input
                                        panelTreeRef?.current?.focusItem(visibleItems[0].id)
                                    }
                                }
                            }}
                        />
                    </div>
                    <div className="border-b border-primary h-px" />
                    {children}
                </div>
            </nav>
        </>
    )
}
