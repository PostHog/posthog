import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconChevronDown, IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'

import { InsightLogicProps, InsightType } from '~/types'

import { InsightsNav } from '../InsightsNav'
import { CORE_TYPES, EXTRA_TYPES, ExtraTypeEntry } from './SidebarTypeCardPrototype'

/**
 * THROWAWAY PROTOTYPE: do not ship, do not extend.
 *
 * Question: can the insight type tab strip be replaced with something that scales to more
 * insight types? Usage data says the strip is mostly used to pick a type right after opening
 * the editor (or to browse adjacent tabs), while a minority converts an already-configured
 * insight and relies on the config carry-over in insightNavLogic.
 *
 * Five variants of the type switcher on the real insight editor route (edit mode), switchable
 * via `?variant=` or the floating bar at the bottom (arrow keys cycle too):
 *   tabs     : baseline: today's tab strip
 *   dropdown : one compact type select where the tabs sat
 *   hybrid   : Trends + Funnels stay as tabs, everything else behind a "More types" menu
 *   palette  : no persistent strip: a type chip that opens a searchable picker dialog
 *   sidebar  : nothing in the header at all: a type + view card above the filters in the left
 *              sidebar (see SidebarTypeCardPrototype.tsx, rendered from EditorFilters)
 *   sidebar-questions : sidebar families grouped by the question asked (stickiness and
 *              lifecycle under retention)
 *   sidebar-families  : sidebar families grouped by shared setup (stickiness and lifecycle
 *              under trends, retention splits recurring vs first time)
 *   sidebar-modes     : sidebar, no regrouping: the six types in a select plus a uniform
 *              mode row surfacing each type's buried subtype picker
 *   sidebar-sketches / sidebar-list / sidebar-compact : visual alternatives of the sidebar
 *              card; same grouping as sidebar-families, only the looks change (sketch
 *              gallery, quiet indented list, two bare selects)
 *   sidebar-section : a native "Visualization" section styled like General/Filters; a
 *              carousel of sketch cards with descriptions, where the display menu's groups
 *              are the top level (time series, total value, world map, calendar heatmap,
 *              funnel, retention, ...) with display suboptions
 *   sidebar-viz-grid : G's tinted card filled with L's viz-first options as a sketch grid,
 *              all nine visible at once with "View as" suboptions below
 *
 * The real six types switch for real (same setActiveView as the tab strip, carry-over intact).
 * Extra entries (calendar heatmap, SQL, examples) are display-only, there to show how each
 * variant copes with a longer type list. The winning variant gets rebuilt properly (quill
 * Select/Combobox, kea logic, analytics); everything in this folder gets deleted.
 */

interface VariantProps {
    insightLogicProps: InsightLogicProps
}

function coreOption(type: InsightType): {
    value: string
    label: string
    icon: JSX.Element
    labelInMenu: JSX.Element
} {
    const meta = INSIGHT_TYPES_METADATA[type]
    const Icon = meta.icon
    return {
        value: type,
        label: meta.name,
        icon: <Icon />,
        labelInMenu: (
            <div className="flex max-w-md flex-col py-0.5">
                <span className="font-semibold">{meta.name}</span>
                <span className="text-secondary text-xs">{meta.description}</span>
            </div>
        ),
    }
}

function extraOption(entry: ExtraTypeEntry): {
    value: string
    label: string
    icon: JSX.Element
    disabledReason: string
    labelInMenu: JSX.Element
} {
    const Icon = entry.icon
    return {
        value: entry.key,
        label: entry.name,
        icon: <Icon />,
        disabledReason: entry.disabledReason,
        labelInMenu: (
            <div className="flex max-w-md flex-col py-0.5">
                <span className="flex items-center gap-2 font-semibold">
                    {entry.name}
                    <LemonTag size="small" type="muted">
                        {entry.tag}
                    </LemonTag>
                </span>
                <span className="text-secondary text-xs">{entry.description}</span>
            </div>
        ),
    }
}

/** Variant B: the whole strip collapses into one compact select. */
function DropdownVariant({ insightLogicProps }: VariantProps): JSX.Element {
    const { activeView } = useValues(insightNavLogic(insightLogicProps))
    const { setActiveView } = useActions(insightNavLogic(insightLogicProps))

    const options: LemonSelectOptions<string> = [
        { title: 'Insight type', options: CORE_TYPES.map(coreOption) },
        { title: 'More types', options: EXTRA_TYPES.map(extraOption) },
    ]

    return (
        <div className="mb-2 flex items-center gap-2">
            <LemonSelect
                size="small"
                value={activeView as string}
                onChange={(value) => value && setActiveView(value as InsightType)}
                options={options}
                dropdownMatchSelectWidth={false}
                data-attr="prototype-insight-type-dropdown"
            />
        </div>
    )
}

/** Variant C: the dominant pair stays one click away, the long tail moves behind "More types". */
function HybridVariant({ insightLogicProps }: VariantProps): JSX.Element {
    const { activeView } = useValues(insightNavLogic(insightLogicProps))
    const { setActiveView } = useActions(insightNavLogic(insightLogicProps))

    const primary: InsightType[] = [InsightType.TRENDS, InsightType.FUNNELS]
    const tabTypes = primary.includes(activeView) ? primary : [...primary, activeView]
    const moreOptions: LemonSelectOptions<string | null> = [
        {
            title: 'More types',
            options: [
                ...CORE_TYPES.filter((type) => !primary.includes(type)).map(coreOption),
                ...EXTRA_TYPES.map(extraOption),
            ],
        },
    ]

    return (
        <div className="flex items-center gap-2 [&_.LemonTabs]:![--lemon-tabs-margin-bottom:0]">
            <LemonTabs
                activeKey={activeView}
                onChange={(view) => setActiveView(view)}
                tabs={tabTypes.map((type) => ({ key: type, label: INSIGHT_TYPES_METADATA[type].name }))}
            />
            <LemonSelect<string | null>
                size="small"
                placeholder="More types"
                value={null}
                onChange={(value) => value && setActiveView(value as InsightType)}
                options={moreOptions}
                dropdownMatchSelectWidth={false}
                data-attr="prototype-insight-type-more"
            />
        </div>
    )
}

/** Variant D: no persistent strip at all: a chip that opens a searchable picker dialog. */
function PaletteVariant({ insightLogicProps }: VariantProps): JSX.Element {
    const { activeView } = useValues(insightNavLogic(insightLogicProps))
    const { setActiveView } = useActions(insightNavLogic(insightLogicProps))
    const [isOpen, setIsOpen] = useState(false)
    const [search, setSearch] = useState('')

    const activeMeta = INSIGHT_TYPES_METADATA[activeView] ?? INSIGHT_TYPES_METADATA[InsightType.TRENDS]
    const ActiveIcon = activeMeta.icon

    const entries = [
        ...CORE_TYPES.map((type) => ({
            key: type as string,
            name: INSIGHT_TYPES_METADATA[type].name,
            description: INSIGHT_TYPES_METADATA[type].description ?? '',
            icon: INSIGHT_TYPES_METADATA[type].icon,
            tag: null as string | null,
        })),
        ...EXTRA_TYPES.map((entry) => ({
            key: entry.key,
            name: entry.name,
            description: entry.description,
            icon: entry.icon,
            tag: entry.tag,
        })),
    ]
    const filtered = entries.filter((entry) =>
        `${entry.name} ${entry.description}`.toLowerCase().includes(search.toLowerCase())
    )

    const close = (): void => {
        setIsOpen(false)
        setSearch('')
    }

    return (
        <div className="mb-2 flex items-center gap-2">
            <LemonButton
                type="secondary"
                size="small"
                icon={<ActiveIcon />}
                sideIcon={<IconChevronDown />}
                onClick={() => setIsOpen(true)}
                data-attr="prototype-insight-type-chip"
            >
                {activeMeta.name}
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={close}
                title="Change insight type"
                description="Your configuration carries over where the new type supports it."
                width={720}
            >
                <div className="flex flex-col gap-4">
                    <LemonInput
                        type="search"
                        autoFocus
                        fullWidth
                        placeholder="Search insight types…"
                        value={search}
                        onChange={setSearch}
                    />
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {filtered.map((entry) => {
                            const EntryIcon = entry.icon
                            const isSelectable = entry.tag === null
                            const content = (
                                <>
                                    <span className="shrink-0 text-xl">
                                        <EntryIcon />
                                    </span>
                                    <div className="min-w-0">
                                        <div className="flex items-center gap-2 font-semibold">
                                            {entry.name}
                                            {entry.tag && (
                                                <LemonTag size="small" type="muted">
                                                    {entry.tag}
                                                </LemonTag>
                                            )}
                                        </div>
                                        <div className="text-secondary text-xs">{entry.description}</div>
                                    </div>
                                </>
                            )
                            return isSelectable ? (
                                <LemonCard
                                    key={entry.key}
                                    focused={entry.key === activeView}
                                    onClick={() => {
                                        setActiveView(entry.key as InsightType)
                                        close()
                                    }}
                                    className="flex cursor-pointer items-start gap-3 p-3"
                                    data-attr={`prototype-insight-type-card-${entry.key.toLowerCase()}`}
                                >
                                    {content}
                                </LemonCard>
                            ) : (
                                <LemonCard
                                    key={entry.key}
                                    hoverEffect={false}
                                    className="flex items-start gap-3 p-3 opacity-60"
                                >
                                    {content}
                                </LemonCard>
                            )
                        })}
                        {filtered.length === 0 && (
                            <div className="text-secondary col-span-full p-4 text-center">
                                No matching insight types
                            </div>
                        )}
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}

const VARIANTS = [
    { key: 'tabs', name: 'Baseline: tab strip' },
    { key: 'dropdown', name: 'Compact dropdown' },
    { key: 'hybrid', name: 'Hot-path tabs + More' },
    { key: 'palette', name: 'Chip + searchable picker' },
    { key: 'sidebar', name: 'Sidebar type + view card' },
    { key: 'sidebar-questions', name: 'Sidebar: question families' },
    { key: 'sidebar-families', name: 'Sidebar: shared-editor families' },
    { key: 'sidebar-modes', name: 'Sidebar: flat + mode row' },
    { key: 'sidebar-sketches', name: 'Sidebar visual: sketch gallery' },
    { key: 'sidebar-list', name: 'Sidebar visual: quiet list' },
    { key: 'sidebar-compact', name: 'Sidebar visual: compact selects' },
    { key: 'sidebar-section', name: 'Sidebar: native section, viz carousel' },
    { key: 'sidebar-viz-grid', name: 'Sidebar: viz grid (G card, L options)' },
] as const

export function InsightTypeSwitcherPrototype({ insightLogicProps }: VariantProps): JSX.Element {
    const { location, searchParams, hashParams } = useValues(router)
    const { activeView } = useValues(insightNavLogic(insightLogicProps))

    const requested = typeof searchParams.variant === 'string' ? searchParams.variant : 'tabs'
    const index = Math.max(
        0,
        VARIANTS.findIndex((variant) => variant.key === requested)
    )
    const variant = VARIANTS[index]

    const setVariant = (key: string): void => {
        router.actions.replace(location.pathname, { ...searchParams, variant: key }, hashParams)
    }
    const cycle = (delta: number): void => {
        setVariant(VARIANTS[(index + delta + VARIANTS.length) % VARIANTS.length].key)
    }

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
                return
            }
            const target = event.target as HTMLElement | null
            // Leave arrow keys alone inside inputs, menus, and modals, where they navigate.
            if (
                target?.closest(
                    'input, textarea, select, [contenteditable="true"], [role="menu"], [role="listbox"], [role="dialog"], .Popover'
                )
            ) {
                return
            }
            cycle(event.key === 'ArrowRight' ? 1 : -1)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    })

    return (
        <>
            {variant.key === 'tabs' && (
                <div className="[&_.LemonTabs]:![--lemon-tabs-margin-bottom:0]">
                    <InsightsNav />
                </div>
            )}
            {variant.key === 'dropdown' && <DropdownVariant insightLogicProps={insightLogicProps} />}
            {variant.key === 'hybrid' && <HybridVariant insightLogicProps={insightLogicProps} />}
            {variant.key === 'palette' && <PaletteVariant insightLogicProps={insightLogicProps} />}

            {process.env.NODE_ENV !== 'production' && (
                <div className="border-primary bg-surface-primary fixed bottom-4 left-1/2 z-[1000] flex -translate-x-1/2 items-center gap-1 rounded-full border py-1 pr-2 pl-1 shadow-lg">
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronLeft />}
                        onClick={() => cycle(-1)}
                        tooltip="Previous variant (←)"
                    />
                    <span className="text-xs font-semibold whitespace-nowrap">
                        {String.fromCharCode(65 + index)} · {variant.name}
                    </span>
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronRight />}
                        onClick={() => cycle(1)}
                        tooltip="Next variant (→)"
                    />
                    <LemonTag type="highlight">{INSIGHT_TYPES_METADATA[activeView]?.name ?? activeView}</LemonTag>
                </div>
            )}
        </>
    )
}
