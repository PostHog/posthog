import { IconCheck, IconFilter, IconPin, IconPinFilled } from '@posthog/icons'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { getTreeFilterTypes } from '~/products'
import { FileSystemFilterType } from '~/types'

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
}

const panelLayoutPanelVariants = cva({
    base: 'w-full flex flex-col max-h-screen min-h-screen relative border-r border-primary transition-[width] duration-100 prefers-reduced-motion:transition-none',
    variants: {
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

interface FiltersDropdownProps {
    setSearchTerm: (searchTerm: string) => void
    searchTerm: string
}

export function FiltersDropdown({ setSearchTerm, searchTerm }: FiltersDropdownProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const types: [string, FileSystemFilterType][] = [
        ...Object.entries(getTreeFilterTypes()),
        ['destination', { name: 'Destinations' }],
        ['site_app', { name: 'Site apps' }],
        ['source', { name: 'Sources' }],
        ['transformation', { name: 'Transformations' }],
    ]
    const removeTagsStarting = (str: string, tag: string): string =>
        str
            .split(' ')
            .filter((p) => !p.startsWith(tag))
            .join(' ')
            .trim()
    const removeTagsEquals = (str: string, tag: string): string =>
        str
            .split(' ')
            .filter((p) => p != tag)
            .join(' ')
            .trim()
    const addTag = (str: string, tag: string): string => `${str.trim()} ${tag.trim()}`.trim()

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    iconOnly
                    className="z-2 shrink-0 motion-safe:transition-opacity duration-[50ms] group-hover/lemon-tree-button-group:opacity-100 aria-expanded:opacity-100"
                >
                    <IconFilter className="size-3 text-tertiary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                <DropdownMenuGroup>
                    <DropdownMenuItem
                        onClick={(e) => {
                            e.preventDefault()
                            setSearchTerm(
                                searchTerm.includes('user:me')
                                    ? removeTagsEquals(searchTerm, 'user:me')
                                    : addTag(searchTerm, 'user:me')
                            )
                        }}
                    >
                        <ButtonPrimitive menuItem>
                            {searchTerm.includes('user:me') ? <IconCheck /> : <IconBlank />}
                            Only my stuff
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    {types
                        .filter(([_, { flag }]) => !flag || featureFlags[flag as keyof typeof featureFlags])
                        .map(([obj, { name }]) => (
                            <DropdownMenuItem
                                key={obj}
                                onClick={(e) => {
                                    e.preventDefault()
                                    setSearchTerm(
                                        searchTerm.includes(`type:${obj}`)
                                            ? removeTagsStarting(searchTerm, 'type:')
                                            : addTag(removeTagsStarting(searchTerm, 'type:'), `type:${obj}`)
                                    )
                                }}
                            >
                                <ButtonPrimitive menuItem>
                                    {searchTerm.includes(`type:${obj}`) ? <IconCheck /> : <IconBlank />}
                                    {name}
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export function PanelLayoutPanel({
    searchField,
    panelActions,
    children,
    filterDropdown,
}: PanelLayoutPanelProps): JSX.Element {
    const { toggleLayoutPanelPinned, setPanelWidth, setPanelIsResizing } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelPinned,
        isLayoutNavCollapsed,
        panelWidth: computedPanelWidth,
        panelWillHide,
    } = useValues(panelLayoutLogic)
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
            <div className="z-main-nav flex flex-1 flex-col justify-between overflow-y-auto bg-surface-secondary group/colorful-product-icons colorful-product-icons-true">
                {searchField || filterDropdown ? (
                    <>
                        <div className="flex gap-1 p-1 items-center justify-between">
                            {searchField ?? null}
                            {filterDropdown ?? null}
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
            key="panel-layout-panel"
            defaultWidth={computedPanelWidth}
            onResize={(width) => {
                setPanelWidth(width)
            }}
            aria-label="Resize handle for panel layout panel"
            borderPosition="right"
            innerClassName="z-[var(--z-layout-panel)]"
            onResizeStart={() => setPanelIsResizing(true)}
            onResizeEnd={() => setPanelIsResizing(false)}
        >
            {panelContents}
        </ResizableElement>
    )
}
