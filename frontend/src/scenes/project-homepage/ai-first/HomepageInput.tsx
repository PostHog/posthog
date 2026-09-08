import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconArrowRight, IconClock, IconInfo, IconMicrophone, IconPin, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { Search } from 'lib/components/Search/Search'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { cn } from 'lib/utils/css-classes'
import { uuid } from 'lib/utils/dom'
import { FillInHint } from 'scenes/max/components/FillInHint'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { SuggestionCard } from 'scenes/max/components/SuggestionCard'
import { SUGGESTION_CARDS_HEIGHT_PX, COLORFUL_ICONS, TopicBadges } from 'scenes/max/components/TopicBadges'
import { handsFreeLogic } from 'scenes/max/handsFreeLogic'
import { Intro } from 'scenes/max/Intro'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { HOMEPAGE_SUGGESTION_TOPICS } from 'scenes/max/suggestionTopics'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIconWrapper, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import {
    HomepageGridItem,
    HomepageGridItemKind,
    PINNED_DASHBOARDS_LIMIT,
    RAIL_ROW_BUDGET,
    aiFirstHomepageLogic,
} from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'
import { SUGGESTIONS_LIMIT } from './homepageSuggestions'

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
        // The input stays at readable width even when the idle scene around it is wider
        <form onSubmit={handleSubmit} className="flex flex-col items-center w-full max-w-180 mx-auto px-3">
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

export function HomepageAiInput(): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { acceptDataProcessing } = useAsyncActions(aiConsentLogic)
    const [approving, setApproving] = useState(false)

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
                    {isAdmin
                        ? 'PostHog AI needs your approval to potentially process identifying user data with external AI providers.'
                        : 'PostHog AI needs an organization admin to approve processing identifying user data with external AI providers.'}
                </p>
                <p className="text-muted text-xs m-0">Your data won't be used for training third-party models.</p>
                {isAdmin ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={approving}
                        onClick={() => {
                            setApproving(true)
                            void acceptDataProcessing()
                                .catch(console.error)
                                .finally(() => setApproving(false))
                        }}
                        sideIcon={<IconArrowRight />}
                    >
                        I allow AI analysis in this organization
                    </LemonButton>
                ) : (
                    <div className="flex">
                        <AIAccessRequest size="small" />
                    </div>
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
    if (item.icon) {
        return <>{item.icon}</>
    }
    if (item.itemType) {
        return (
            <ProductIconWrapper type={item.itemType}>
                {iconForType(item.itemType as FileSystemIconType)}
            </ProductIconWrapper>
        )
    }
    if (item.kind === 'suggestion') {
        return <IconSparkles className="text-tertiary" />
    }
    return null
}

interface RailSection {
    label: string
    kind: HomepageGridItemKind
    icon: React.ReactNode
    /** Copy for the resolved-but-empty state. A section without it hides entirely when empty. */
    emptyState?: { label: string; tooltip: React.ReactNode }
}

// The navigation rail next to the suggestions list: compact links to existing resources.
// Recents carry no empty state: they fill by themselves as the user browses, so an empty
// section has nothing actionable to say and just takes space.
const RAIL_SECTIONS: RailSection[] = [
    {
        label: 'Pinned dashboards',
        kind: 'dashboard',
        icon: <IconPin className="size-3" />,
        emptyState: {
            label: 'No pinned dashboards',
            tooltip: 'Pin dashboards by clicking "Pin" in the dashboard context panel',
        },
    },
    {
        label: 'Recents',
        kind: 'recent',
        icon: <IconClock className="size-3" />,
    },
]

const SKELETON_ROWS_BY_KIND: Record<HomepageGridItemKind, number> = {
    dashboard: PINNED_DASHBOARDS_LIMIT,
    // Recents share the rail budget with pinned dashboards, so their guaranteed floor is
    // whatever a full pinned section leaves over
    recent: RAIL_ROW_BUDGET - PINNED_DASHBOARDS_LIMIT,
    suggestion: SUGGESTIONS_LIMIT,
}

const GRID_SKELETON_COUNTS_KEY = 'homepage-grid-skeleton-counts'

function getStoredSkeletonCounts(): Record<string, number> | null {
    try {
        const stored = localStorage.getItem(GRID_SKELETON_COUNTS_KEY)
        return stored ? JSON.parse(stored) : null
    } catch {
        return null
    }
}

interface GridRowProps {
    item: HomepageGridItem
    highlighted: boolean
    onHighlight: (highlighted: boolean) => void
}

function GridRow({ item, highlighted, onHighlight }: GridRowProps): JSX.Element {
    const { gridItemClicked, activateGridItem } = useActions(aiFirstHomepageLogic)
    return (
        <div role="row">
            <Link
                to={item.href}
                role="gridcell"
                title={item.label}
                buttonProps={{
                    menuItem: true,
                    fullWidth: true,
                    className: 'truncate -outline-offset-2',
                }}
                // Items with an href navigate through the anchor itself, so the click handler
                // only reports; suggestions have no href and the handler performs the action too.
                onClick={() => (item.href ? gridItemClicked(item) : activateGridItem(item))}
                data-attr={`homepage-grid-${item.kind}`}
                data-highlighted={highlighted ? 'true' : undefined}
                onMouseEnter={() => onHighlight(true)}
                onMouseLeave={() => onHighlight(false)}
            >
                <GridItemIcon item={item} />
                <span className="truncate">{item.label}</span>
            </Link>
        </div>
    )
}

function SuggestionRow({ item, highlighted, onHighlight }: GridRowProps): JSX.Element {
    const { activateGridItem } = useActions(aiFirstHomepageLogic)
    return (
        // data-highlighted lives on the wrapper so keyboard navigation can scroll to it;
        // the visual highlight rides the card's own active state.
        <div role="row" data-highlighted={highlighted ? 'true' : undefined}>
            <SuggestionCard
                title={item.label}
                description={item.description}
                icon={<GridItemIcon item={item} />}
                onClick={() => activateGridItem(item)}
                active={highlighted}
                data-attr={`homepage-grid-${item.kind}`}
                onMouseEnter={() => onHighlight(true)}
                onMouseLeave={() => onHighlight(false)}
            />
        </div>
    )
}

function GridSkeletons({
    kind,
    counts,
}: {
    kind: HomepageGridItemKind
    counts: Record<string, number> | null
}): JSX.Element {
    // Stored counts can predate the current row caps, so clamp to keep the layout stable
    const rows = Math.min(counts?.[kind] ?? SKELETON_ROWS_BY_KIND[kind], SKELETON_ROWS_BY_KIND[kind])
    return (
        <>
            {Array.from({ length: rows }).map((_, i) => (
                <div key={`skeleton-${i}`}>
                    {/* Suggestion cards are two-line units, taller than the single-line rail rows */}
                    <LemonSkeleton className={kind === 'suggestion' ? 'h-[45px]' : 'h-[30px]'} />
                </div>
            ))}
        </>
    )
}

function RailEmptyState({
    kind,
    emptyState,
}: {
    kind: HomepageGridItemKind
    emptyState: NonNullable<RailSection['emptyState']>
}): JSX.Element {
    return (
        <div
            className="px-3 py-2 border border-dashed rounded text-xs text-tertiary"
            data-attr={`homepage-grid-empty-${kind}`}
        >
            {emptyState.label}{' '}
            <Tooltip title={emptyState.tooltip} delayMs={0}>
                <IconInfo className="size-3 text-tertiary" data-attr={`homepage-grid-empty-tooltip-${kind}`} />
            </Tooltip>
        </div>
    )
}

function IdleGrid(): JSX.Element {
    const {
        gridItems,
        displayedSuggestionItems,
        query,
        dashboardsLoading,
        recentItemsLoading,
        suggestionItemsLoading,
        selectedTopic,
    } = useValues(aiFirstHomepageLogic)
    const { activateGridItem } = useActions(aiFirstHomepageLogic)

    // [col, row] position of the highlighted item, null = nothing highlighted.
    // Column 0 is the suggestions list, column 1 the whole rail (dashboards then recents).
    const [highlight, setHighlight] = useState<[number, number] | null>(null)
    const gridRef = useRef<HTMLDivElement>(null)

    const [skeletonCounts, setSkeletonCounts] = useState(getStoredSkeletonCounts)

    const railItemsByKind = useMemo(
        () => ({
            dashboard: gridItems.filter((item) => item.kind === 'dashboard'),
            recent: gridItems.filter((item) => item.kind === 'recent'),
        }),
        [gridItems]
    )

    const columns = useMemo(
        () => [
            { key: 'suggestions', items: displayedSuggestionItems },
            { key: 'rail', items: [...railItemsByKind.dashboard, ...railItemsByKind.recent] },
        ],
        [displayedSuggestionItems, railItemsByKind]
    )

    // Persist item counts when loading finishes so skeletons match on next visit
    useEffect(() => {
        const isLoading = dashboardsLoading || recentItemsLoading || suggestionItemsLoading
        if (isLoading) {
            return
        }
        const counts: Record<string, number> = {
            dashboard: railItemsByKind.dashboard.length,
            recent: railItemsByKind.recent.length,
            suggestion: displayedSuggestionItems.length,
        }
        localStorage.setItem(GRID_SKELETON_COUNTS_KEY, JSON.stringify(counts))
        setSkeletonCounts(counts)
    }, [dashboardsLoading, recentItemsLoading, suggestionItemsLoading, railItemsByKind, displayedSuggestionItems])

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
                        activateGridItem(item)
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
        [highlight, columns, activateGridItem]
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

    const railHighlightOffset: Record<'dashboard' | 'recent', number> = {
        dashboard: 0,
        recent: railItemsByKind.dashboard.length,
    }

    // Collapse-on-typing is handled by the shared wrapper in HomepageInput, so this renders the
    // grid content directly (no self-collapse), keeping the badges and grid in one animated box.
    return (
        <div
            ref={gridRef}
            role="grid"
            data-attr="homepage-grid"
            // Only shown at @xl+ where the suggestions list and the rail sit side by side.
            // shrink-0 so the collapse-on-typing animation clips instead of squeezing.
            className="flex gap-6 w-full px-3 outline-none shrink-0"
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
            {/* Suggestions list, or the selected topic's suggestions in the same slot */}
            <div
                role="rowgroup"
                className={cn('flex-[2] min-w-0 flex flex-col gap-px', COLORFUL_ICONS)}
                data-attr="homepage-grid-column-suggestion"
                style={{ minHeight: SUGGESTION_CARDS_HEIGHT_PX }}
            >
                <Label className="px-2 mb-1 flex items-center gap-1" intent="menu">
                    <IconSparkles className="size-3" />
                    Ask PostHog AI
                </Label>
                {/* The static fill means the list is never empty, so gate on the sources
                    having resolved; a selected topic is static data and never loads */}
                {!selectedTopic && suggestionItemsLoading ? (
                    <GridSkeletons kind="suggestion" counts={skeletonCounts} />
                ) : (
                    displayedSuggestionItems.map((item, rowIndex) => (
                        <SuggestionRow
                            key={item.id}
                            item={item}
                            highlighted={highlight?.[0] === 0 && highlight?.[1] === rowIndex}
                            onHighlight={(over) => setHighlight(over ? [0, rowIndex] : null)}
                        />
                    ))
                )}
            </div>

            {/* Navigation rail: pinned dashboards and recents */}
            <div role="rowgroup" className="flex-1 min-w-0 flex flex-col gap-px" data-attr="homepage-grid-column-nav">
                {RAIL_SECTIONS.map((section) => {
                    const items = railItemsByKind[section.kind as 'dashboard' | 'recent']
                    const loading = section.kind === 'dashboard' ? dashboardsLoading : recentItemsLoading
                    const offset = railHighlightOffset[section.kind as 'dashboard' | 'recent']
                    if (!loading && items.length === 0 && !section.emptyState) {
                        return null
                    }
                    return (
                        <div key={section.kind} className="flex flex-col gap-px [&:not(:first-child)]:mt-3">
                            <Label className="px-2 mb-1 flex items-center gap-1" intent="menu">
                                {section.icon}
                                {section.label}
                            </Label>
                            {loading && items.length === 0 ? (
                                <GridSkeletons kind={section.kind} counts={skeletonCounts} />
                            ) : items.length === 0 && section.emptyState ? (
                                <RailEmptyState kind={section.kind} emptyState={section.emptyState} />
                            ) : (
                                items.map((item, index) => (
                                    <GridRow
                                        key={item.id}
                                        item={item}
                                        highlighted={highlight?.[0] === 1 && highlight?.[1] === offset + index}
                                        onHighlight={(over) => setHighlight(over ? [1, offset + index] : null)}
                                    />
                                ))
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

export function HomepageInput(): JSX.Element {
    const { mode, query, selectedTopic } = useValues(aiFirstHomepageLogic)
    const { setSelectedTopic } = useActions(aiFirstHomepageLogic)
    const { user } = useValues(userLogic)

    return (
        // Idle gets extra width for the suggestions grid; AI and search keep the chat width
        <div className={cn('w-full mx-auto py-2', mode === 'idle' ? 'max-w-240' : 'max-w-180')}>
            {mode === 'idle' && (
                <div className="flex flex-col items-center gap-3 pb-(--scene-layout-header-height)">
                    <Intro forceHeadline={`Hello ${user?.first_name || 'there'}`} forceSubheadline={null} />
                    <IdleInput />
                    {/* Badges + grid collapse together as a single box when the user starts typing /
                        leaves idle. Hidden on mobile — only shown at @xl, where the suggestions list
                        and the rail sit side by side. */}
                    <div
                        className="w-full hidden @xl/main-content:grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:duration-0"
                        style={{ gridTemplateRows: query.trim() ? '0fr' : '1fr' }}
                        aria-hidden={!!query.trim()}
                    >
                        {/* shrink-0 on the children so collapsing just clips them away (top-down) rather
                            than squeezing their heights, which would reflow the grid mid-animation.
                            gap-6 spaces the badges from the row below — it's part of the flex column's
                            laid-out height, so it's counted in the collapse and the vertical centering. */}
                        <div className="overflow-hidden flex flex-col items-center gap-6">
                            <TopicBadges
                                className="shrink-0"
                                topics={HOMEPAGE_SUGGESTION_TOPICS}
                                selectedKey={selectedTopic}
                                onSelect={setSelectedTopic}
                            />
                            <IdleGrid />
                        </div>
                    </div>
                </div>
            )}
            {mode === 'ai' && <HomepageAiInput />}
            {mode === 'search' && <Search.Input autoFocus />}
        </div>
    )
}
