import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconArrowRight, IconClock, IconInfo, IconLock, IconMicrophone, IconPin, IconStar } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { Search } from 'lib/components/Search/Search'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { cn } from 'lib/utils/css-classes'
import { uuid } from 'lib/utils/dom'
import {
    CAPABILITY_CARDS_HEIGHT_PX,
    CapabilityBadges,
    CapabilitySuggestions,
} from 'scenes/max/components/CapabilityBadges'
import { FillInHint } from 'scenes/max/components/FillInHint'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { handsFreeLogic } from 'scenes/max/handsFreeLogic'
import { Intro } from 'scenes/max/Intro'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { HomepageGridItem, HomepageGridItemKind, aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'

function IdleInput(): JSX.Element {
    const { query, fillInHint } = useValues(aiFirstHomepageLogic)
    const { setQuery, submitQuery, enterAiMode, startHandsFreeChat, setFillInHint } = useActions(aiFirstHomepageLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const handsFreeFlag = useFeatureFlag('MAX_HANDS_FREE')
    const { canUseHandsFree } = useValues(handsFreeLogic({ panelId: HOMEPAGE_TAB_ID }))
    const inputRef = useRef<HTMLTextAreaElement>(null)

    const handsFreeAvailable = handsFreeFlag && canUseHandsFree && dataProcessingAccepted
    // A fill-in suggestion typed its prefix in and is waiting for the user to complete it.
    const showFillInHint = !!fillInHint

    useEffect(() => {
        const timer = setTimeout(() => inputRef.current?.focus(), 100)
        return () => clearTimeout(timer)
    }, [])

    const submitAi = (): void => {
        if (!query.trim()) {
            return
        }
        posthog.capture('homepage query submitted', { mode: 'ai' })
        submitQuery('ai')
    }

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        submitAi()
    }

    return (
        <form onSubmit={handleSubmit} className="flex flex-col items-center w-full px-3">
            <label
                htmlFor="homepage-input"
                className="min-h-[40px] group input-like flex flex-col items-start relative w-full bg-fill-input border border-primary focus-within:ring-primary rounded-lg justify-stretch overflow-hidden"
            >
                <div className="flex w-full py-1 px-1 max-h-[300px] items-end gap-1">
                    {!query && !fillInHint && (
                        <span className="text-tertiary pointer-events-none absolute left-2.5 top-2 flex items-center gap-1">
                            <span className="text-tertiary">What can I help you with?</span>
                            <span className="text-tertiary opacity-50 contrast-more:opacity-100 hidden @xl/main-content:inline">
                                / for commands
                            </span>
                        </span>
                    )}
                    {/* Postfix cue after the typed-in prefix (aligned to the textarea text origin). */}
                    {fillInHint && (
                        <span className="pointer-events-none absolute left-2 top-2 right-2 overflow-hidden">
                            <FillInHint text={query} hint={fillInHint} />
                        </span>
                    )}
                    <TextareaPrimitive
                        ref={inputRef}
                        id="homepage-input"
                        data-attr="homepage-input"
                        wrapperClassName="flex-1 min-w-0"
                        value={query}
                        onChange={(e) => {
                            const value = e.target.value
                            // Typing / or @ as the first character enters AI mode without sending
                            if (value === '/' || value === '@') {
                                posthog.capture('homepage ai mode entered', { trigger: value })
                                enterAiMode(value)
                                return
                            }
                            // The user typing their own text ends the fill-in cue.
                            if (fillInHint) {
                                setFillInHint(null)
                            }
                            setQuery(value)
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Tab' && query.trim()) {
                                e.preventDefault()
                                posthog.capture('homepage query submitted', { mode: 'search' })
                                submitQuery('search')
                            }
                            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                                if (e.shiftKey) {
                                    // Allow default behavior to insert newline
                                    return
                                }
                                // Prevent newline, let form submit handle it
                                e.preventDefault()
                                submitAi()
                            }
                            if (e.key === 'Escape' && (query.trim() || fillInHint)) {
                                e.preventDefault()
                                setQuery('')
                                setFillInHint(null)
                            }
                            // When input is empty, ArrowDown moves focus to the grid
                            if (e.key === 'ArrowDown' && !query.trim()) {
                                const grid = document.querySelector<HTMLElement>('[data-attr="homepage-grid"]')
                                if (grid) {
                                    e.preventDefault()
                                    grid.dataset.keyboardFocus = 'true'
                                    grid.focus()
                                }
                            }
                        }}
                        autoComplete="off"
                        className={cn(
                            'w-full px-1 py-1 text-sm focus:outline-none border-transparent resize-none bg-transparent',
                            // Hide the native caret so only the enlarged fill-in caret shows.
                            showFillInHint && 'caret-transparent'
                        )}
                        autoFocus
                    />
                    <div className="flex items-end shrink-0">
                        <div className="flex items-center gap-1">
                            <ButtonPrimitive
                                size="xs"
                                className="text-tertiary hover:text-primary shrink-0"
                                onClick={() => {
                                    posthog.capture('homepage query submitted', { mode: 'search' })
                                    submitQuery('search')
                                }}
                            >
                                <span className="text-xxs">Tab to search</span>
                            </ButtonPrimitive>
                            {handsFreeAvailable && (
                                <Tooltip title="Start a new chat in hands-free">
                                    <ButtonPrimitive
                                        iconOnly
                                        data-attr="homepage-hands-free"
                                        className="shrink-0"
                                        onClick={startHandsFreeChat}
                                    >
                                        <IconMicrophone className="size-4" />
                                    </ButtonPrimitive>
                                </Tooltip>
                            )}
                            <Tooltip title={!query.trim() ? 'Try asking a question' : undefined}>
                                <ButtonPrimitive
                                    onClick={() => {
                                        posthog.capture('homepage query submitted', { mode: 'ai' })
                                        submitQuery('ai')
                                    }}
                                    iconOnly
                                    className="-mr-0.5 shrink-0"
                                    disabled={!query.trim()}
                                >
                                    <IconArrowRight className="size-4" />
                                </ButtonPrimitive>
                            </Tooltip>
                        </div>
                    </div>
                </div>
            </label>
        </form>
    )
}

function HomepageAiInput(): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { acceptDataProcessing } = useAsyncActions(maxGlobalLogic)

    const fallbackConversationId = useMemo(() => uuid(), [])
    const threadProps: MaxThreadLogicProps = {
        panelId: HOMEPAGE_TAB_ID,
        conversationId: threadLogicKey || fallbackConversationId,
        conversation,
    }

    if (!dataProcessingAccepted) {
        const isAdmin = !dataProcessingApprovalDisabledReason
        return (
            <div className="border border-primary rounded-lg bg-surface-primary p-4 flex flex-col gap-2">
                <p className="font-medium text-pretty m-0">
                    PostHog AI needs your approval to potentially process identifying user data with external AI
                    providers.
                </p>
                <p className="text-muted text-xs m-0">Your data won't be used for training third-party models.</p>
                {isAdmin ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => void acceptDataProcessing().catch(console.error)}
                        sideIcon={<IconArrowRight />}
                    >
                        I allow AI analysis in this organization
                    </LemonButton>
                ) : (
                    <LemonButton type="secondary" size="small" disabled sideIcon={<IconLock />}>
                        {dataProcessingApprovalDisabledReason}
                    </LemonButton>
                )}
            </div>
        )
    }

    return (
        <BindLogic logic={maxThreadLogic} props={threadProps}>
            <SidebarQuestionInput />
        </BindLogic>
    )
}

function GridItemIcon({ item }: { item: HomepageGridItem }): JSX.Element | null {
    if (item.itemType) {
        return (
            <ProductIconWrapper type={item.itemType}>
                {iconForType(item.itemType as FileSystemIconType)}
            </ProductIconWrapper>
        )
    }
    return null
}

interface GridColumn {
    label: string
    kind: HomepageGridItem['kind']
    icon: React.ReactNode
    emptyLabel: string
    emptyTooltip: React.ReactNode
}

const GRID_COLUMNS: GridColumn[] = [
    {
        label: 'Pinned dashboards',
        kind: 'dashboard',
        icon: <IconPin className="size-3" />,
        emptyLabel: 'No pinned dashboards',
        emptyTooltip: 'Pin dashboards by clicking "Pin" in the dashboard context panel',
    },
    {
        label: 'Recents',
        kind: 'recent',
        icon: <IconClock className="size-3" />,
        emptyLabel: 'No recents',
        emptyTooltip: 'Recents are auto-populated when you visit a resource',
    },
    {
        label: 'Starred',
        kind: 'starred',
        icon: <IconStar className="size-3" />,
        emptyLabel: 'No starred items',
        emptyTooltip: 'Add items to starred by clicking "add to starred" in the context panel',
    },
]

const GRID_SKELETON_COUNTS_KEY = 'homepage-grid-skeleton-counts'

function getStoredSkeletonCounts(): Record<string, number> | null {
    try {
        const stored = localStorage.getItem(GRID_SKELETON_COUNTS_KEY)
        return stored ? JSON.parse(stored) : null
    } catch {
        return null
    }
}

function IdleGrid(): JSX.Element {
    const { gridItems, query, dashboardsLoading, recentItemsLoading, starredItemsLoading } =
        useValues(aiFirstHomepageLogic)

    // [col, row] position of the highlighted item, null = nothing highlighted
    const [highlight, setHighlight] = useState<[number, number] | null>(null)
    const gridRef = useRef<HTMLDivElement>(null)

    const [skeletonCounts, setSkeletonCounts] = useState(getStoredSkeletonCounts)

    const hasExtraMarginTop = useFeatureFlag('MAX_HOMEPAGE_CAPABILITIES', 'control')

    const columns = useMemo(() => {
        return GRID_COLUMNS.map((col) => ({
            ...col,
            items: gridItems.filter((item) => item.kind === col.kind),
        }))
    }, [gridItems])

    // Persist item counts when loading finishes so skeletons match on next visit
    useEffect(() => {
        const isLoading = dashboardsLoading || recentItemsLoading || starredItemsLoading
        if (isLoading) {
            return
        }
        const counts: Record<string, number> = {}
        for (const col of columns) {
            counts[col.kind] = col.items.length
        }
        localStorage.setItem(GRID_SKELETON_COUNTS_KEY, JSON.stringify(counts))
        setSkeletonCounts(counts)
    }, [dashboardsLoading, recentItemsLoading, starredItemsLoading, columns])

    const handleItemClick = useCallback((item: HomepageGridItem) => {
        if (item.href) {
            posthog.capture('homepage grid item clicked', { kind: item.kind, href: item.href })
            router.actions.push(item.href)
        }
    }, [])

    // Clear highlight when user starts typing
    useEffect(() => {
        if (query.trim()) {
            setHighlight(null)
        }
    }, [query])

    const handleGridKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            // Only handle keys when the grid div itself is focused (virtual navigation),
            // not when a child link has native focus (e.g. via Tab)
            if (e.target !== e.currentTarget) {
                return
            }

            // Find the next non-empty column in a given direction
            const findNonEmptyCol = (from: number, direction: 1 | -1): number | null => {
                for (let i = from + direction; i >= 0 && i < columns.length; i += direction) {
                    if (columns[i].items.length > 0) {
                        return i
                    }
                }
                return null
            }

            // First navigation into the grid: highlight first non-empty column
            if (!highlight) {
                if (e.key === 'ArrowDown' || e.key === 'ArrowRight' || e.key === 'Enter') {
                    e.preventDefault()
                    const firstCol = columns.findIndex((c) => c.items.length > 0)
                    if (firstCol !== -1) {
                        setHighlight([firstCol, 0])
                    }
                } else if (e.key === 'Escape') {
                    document.querySelector<HTMLElement>('#homepage-input')?.focus()
                }
                return
            }
            const [col, row] = highlight
            const colItems = columns[col].items

            switch (e.key) {
                case 'ArrowDown': {
                    e.preventDefault()
                    if (row < colItems.length - 1) {
                        setHighlight([col, row + 1])
                    }
                    break
                }
                case 'ArrowUp': {
                    e.preventDefault()
                    if (row > 0) {
                        setHighlight([col, row - 1])
                    } else {
                        setHighlight(null)
                        document.querySelector<HTMLElement>('#homepage-input')?.focus()
                    }
                    break
                }
                case 'ArrowRight': {
                    e.preventDefault()
                    const nextCol = findNonEmptyCol(col, 1)
                    if (nextCol !== null) {
                        setHighlight([nextCol, Math.min(row, columns[nextCol].items.length - 1)])
                    }
                    break
                }
                case 'ArrowLeft': {
                    e.preventDefault()
                    const prevCol = findNonEmptyCol(col, -1)
                    if (prevCol !== null) {
                        setHighlight([prevCol, Math.min(row, columns[prevCol].items.length - 1)])
                    }
                    break
                }
                case 'Enter': {
                    e.preventDefault()
                    const item = colItems[row]
                    if (item) {
                        handleItemClick(item)
                    }
                    break
                }
                case 'Escape': {
                    e.preventDefault()
                    setHighlight(null)
                    document.querySelector<HTMLElement>('#homepage-input')?.focus()
                    break
                }
            }
        },
        [highlight, columns, handleItemClick]
    )

    // Scroll highlighted item into view
    useEffect(() => {
        if (!highlight || !gridRef.current) {
            return
        }
        const el = gridRef.current.querySelector('[data-highlighted="true"]')
        if (el) {
            el.scrollIntoView({ block: 'nearest' })
        }
    }, [highlight])

    const loadingByKind: Record<HomepageGridItemKind, boolean> = {
        dashboard: dashboardsLoading,
        recent: recentItemsLoading,
        starred: starredItemsLoading,
    }

    // Collapse-on-typing is handled by the shared wrapper in HomepageInput, so this renders the
    // grid content directly (no self-collapse) — keeping the badges and grid in one animated box.
    return (
        <div
            ref={gridRef}
            role="grid"
            data-attr="homepage-grid"
            // Fills the fixed-height swap container (see HomepageInput) so the recents grid and the
            // capability cards are always the same height. Only shown at @xl+ where columns sit in a row.
            className={cn(
                'flex flex-col @xl/main-content:flex-row gap-8 @xl/main-content:gap-2 w-full px-3 outline-none h-full',
                hasExtraMarginTop && 'mt-2'
            )}
            tabIndex={-1}
            onFocus={(e) => {
                // Only auto-highlight when focused via keyboard (ArrowDown from input)
                if (!highlight && e.currentTarget.dataset.keyboardFocus === 'true') {
                    delete e.currentTarget.dataset.keyboardFocus
                    const firstCol = columns.findIndex((c) => c.items.length > 0)
                    if (firstCol !== -1) {
                        setHighlight([firstCol, 0])
                    }
                }
            }}
            onKeyDown={handleGridKeyDown}
        >
            {columns.map((col, colIndex) => (
                <div
                    key={col.kind}
                    role="rowgroup"
                    className="flex-1 min-w-0 flex flex-col gap-px"
                    data-attr={`homepage-grid-column-${col.kind}`}
                >
                    <Label className="px-2 mb-1 flex items-center gap-1" intent="menu">
                        {col.icon}
                        {col.label}
                    </Label>
                    {loadingByKind[col.kind] &&
                    col.items.length === 0 &&
                    (skeletonCounts === null || (skeletonCounts[col.kind] ?? 0) > 0) ? (
                        Array.from({ length: skeletonCounts?.[col.kind] ?? 3 }).map((_, i) => (
                            <div key={`skeleton-${i}`}>
                                <LemonSkeleton className="h-[30px]" />
                            </div>
                        ))
                    ) : col.items.length === 0 ? (
                        <div
                            className="px-3 py-2 border border-dashed rounded text-xs text-tertiary"
                            data-attr={`homepage-grid-empty-${col.kind}`}
                        >
                            {col.emptyLabel}{' '}
                            <Tooltip title={col.emptyTooltip} delayMs={0}>
                                <IconInfo
                                    className="size-3 text-tertiary"
                                    data-attr={`homepage-grid-empty-tooltip-${col.kind}`}
                                />
                            </Tooltip>
                        </div>
                    ) : (
                        col.items.map((item, rowIndex) => (
                            <div key={item.id} role="row">
                                <Link
                                    to={item.href}
                                    role="gridcell"
                                    title={item.label}
                                    buttonProps={{
                                        menuItem: true,
                                        fullWidth: true,
                                        className: 'truncate -outline-offset-2',
                                    }}
                                    data-attr={`homepage-grid-${item.kind}`}
                                    data-highlighted={
                                        highlight?.[0] === colIndex && highlight?.[1] === rowIndex ? 'true' : undefined
                                    }
                                    onMouseEnter={() => setHighlight([colIndex, rowIndex])}
                                    onMouseLeave={() => setHighlight(null)}
                                >
                                    <GridItemIcon item={item} />
                                    <span className="truncate">{item.label}</span>
                                </Link>
                            </div>
                        ))
                    )}
                </div>
            ))}
        </div>
    )
}

export function HomepageInput(): JSX.Element {
    const { mode, query, capabilities, selectedCapability } = useValues(aiFirstHomepageLogic)
    const { setQuery, submitQuery, setSelectedCapability, setFillInHint } = useActions(aiFirstHomepageLogic)
    const { user } = useValues(userLogic)

    const selectedCapabilityData = capabilities.find((capability) => capability.key === selectedCapability) ?? null

    return (
        <div className="w-full max-w-180 mx-auto py-2 ">
            {mode === 'idle' && (
                <div className="flex flex-col items-center gap-3 pb-(--scene-layout-header-height)">
                    <Intro forceHeadline={`Hello ${user?.first_name || 'there'}`} forceSubheadline={null} />
                    <IdleInput />
                    {/* Badges + (cards | recents grid) collapse together as a single box when the user
                        starts typing / leaves idle. Hidden on mobile — only shown at @xl, where the grid
                        lays its columns in a row. */}
                    <div
                        className="w-full hidden @xl/main-content:grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:duration-0"
                        style={{ gridTemplateRows: query.trim() ? '0fr' : '1fr' }}
                        aria-hidden={!!query.trim()}
                    >
                        {/* shrink-0 on the children so collapsing just clips them away (top-down) rather
                            than squeezing their heights, which would reflow the cards/grid mid-animation.
                            gap-6 spaces the badges from the row below — it's part of the flex column's
                            laid-out height, so it's counted in the collapse and the vertical centering. */}
                        <div className="overflow-hidden flex flex-col gap-6">
                            <CapabilityBadges
                                className="shrink-0"
                                capabilities={capabilities}
                                selectedKey={selectedCapability}
                                onSelect={setSelectedCapability}
                            />
                            {/* Single fixed-height swap area — the cards and the recents grid both fill
                                it (h-full), so switching never changes height. */}
                            <div
                                className="w-full shrink-0 overflow-hidden"
                                style={{ height: CAPABILITY_CARDS_HEIGHT_PX }}
                            >
                                {selectedCapabilityData ? (
                                    <CapabilitySuggestions
                                        capability={selectedCapabilityData}
                                        onType={setQuery}
                                        onSubmit={() => submitQuery('ai')}
                                        onFillIn={(hint) => {
                                            setFillInHint(hint)
                                            document.querySelector<HTMLElement>('#homepage-input')?.focus()
                                        }}
                                    />
                                ) : (
                                    <IdleGrid />
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
            {mode === 'ai' && <HomepageAiInput />}
            {mode === 'search' && <Search.Input autoFocus />}
        </div>
    )
}
