import { IconCheck, IconFilter, IconPin, IconPinFilled } from '@posthog/icons'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
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

// Match with FileSystemViewSet
const productTypes = [
    ['action', 'Actions'],
    ['broadcast', 'Broadcasts'],
    ['campaign', 'Campaigns'],
    ['dashboard', 'Dashboards'],
    ['destination', 'Destinations'],
    ['early_access_feature', 'Early access features'],
    ['experiment', 'Experiments'],
    ['feature_flag', 'Feature flags'],
    ['insight', 'Insights'],
    ['notebook', 'Notebooks'],
    ['session_recording_playlist', 'Replay playlists'],
    ['site_app', 'Site apps'],
    ['source', 'Sources'],
    ['transformation', 'Transformations'],
]

interface PanelLayoutPanelProps {
    searchPlaceholder?: string
    panelActions?: React.ReactNode
    children: React.ReactNode
    showFilterDropdown?: boolean
    searchTerm: string
    clearSearch: () => void
    setSearchTerm: (searchTerm: string) => void
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
                        .filter(([_, { flag }]) => !flag || featureFlags[flag as keyof FeatureFlagsSet])
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
    searchPlaceholder,
    searchTerm,
    clearSearch,
    setSearchTerm,
    panelActions,
    children,
    showFilterDropdown = false,
}: PanelLayoutPanelProps): JSX.Element {
    const { toggleLayoutPanelPinned, setPanelWidth } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelPinned,
        panelTreeRef,
        projectTreeMode,
        isLayoutNavCollapsed,
        panelWidth: computedPanelWidth,
    } = useValues(panelLayoutLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)

    const panelContents = (
        <nav
            className={cn(
                panelLayoutPanelVariants({
                    projectTreeMode: projectTreeMode,
                    isLayoutNavCollapsed,
                    isMobileLayout,
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
                    <SearchAutocomplete
                        inputPlaceholder={searchPlaceholder}
                        includeNegation
                        searchData={[
                            [
                                {
                                    label: 'user',
                                    hint: 'Search by user name',
                                },
                                [{ value: 'me', label: 'Me', hint: 'My stuff' }],
                                'enter a user, quotes are supported',
                            ],
                            [
                                {
                                    label: 'type',
                                    hint: 'Search by type',
                                },
                                productTypes.map(([value, label]) => ({ value, label })),
                                'enter a type',
                            ],
                            [
                                {
                                    label: 'name',
                                    hint: 'Search by item name',
                                },
                                undefined,
                                'enter a name, quotes are supported',
                            ],
                        ]}
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
                        onClear={() => clearSearch()}
                        onChange={(value) => setSearchTerm(value)}
                        autoFocus={true}
                    />
                    {showFilterDropdown && <FiltersDropdown setSearchTerm={setSearchTerm} searchTerm={searchTerm} />}
                </div>
                <div className="border-b border-primary h-px" />
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
        >
            {panelContents}
        </ResizableElement>
    )
}
