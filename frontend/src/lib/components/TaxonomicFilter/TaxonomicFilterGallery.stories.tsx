import { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { ComponentProps, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilter, TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicMenuPreferenceLogic } from 'lib/components/TaxonomicPopover/taxonomicMenuPreferenceLogic'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import {
    DEFAULT_UNIVERSAL_GROUP_FILTER,
    universalFiltersLogic,
} from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'

const noop = (): void => {}

type FilterUsage = { entry: 'filter'; props: Omit<ComponentProps<typeof TaxonomicFilter>, 'taxonomicFilterLogicKey'> }
type PopoverUsage = { entry: 'popover'; props: ComponentProps<typeof TaxonomicPopover> }
type PropertiesUsage = { entry: 'properties'; props: Omit<ComponentProps<typeof PropertyFilters>, 'pageKey'> }
type UniversalUsage = { entry: 'universal'; props: { taxonomicGroupTypes: TaxonomicFilterGroupType[] } }
type SearchUsage = { entry: 'search'; props: { taxonomicGroupTypes: TaxonomicFilterGroupType[] } }

/** One catalogued taxonomic-filter usage: a real scene's entry component + the props it passes. */
type Usage = { name: string; site: string } & (
    | FilterUsage
    | PopoverUsage
    | PropertiesUsage
    | UniversalUsage
    | SearchUsage
)

const G = TaxonomicFilterGroupType

const USAGES: Usage[] = [
    {
        name: 'Insight series picker',
        site: 'ActionFilterRow.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [G.Events, G.Actions, G.DataWarehouse, G.HogQLExpression, G.EventProperties],
            onChange: noop,
        },
    },
    {
        name: 'Insight series property filter',
        site: 'PropertyGroupFilters.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            triggerVariant: 'input',
            eventNames: ['$pageview'],
            hasRowOperator: true,
            allowRelativeDateOptions: true,
            taxonomicGroupTypes: [
                G.EventProperties,
                G.PersonProperties,
                G.EventFeatureFlags,
                G.EventMetadata,
                G.Cohorts,
                G.Elements,
                G.SessionProperties,
                G.HogQLExpression,
            ],
        },
    },
    {
        name: 'Insights breakdown',
        site: 'TaxonomicBreakdownPopover.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [
                G.EventProperties,
                G.PersonProperties,
                G.EventFeatureFlags,
                G.EventMetadata,
                G.CohortsWithAllUsers,
                G.SessionProperties,
                G.HogQLExpression,
                G.DataWarehouseProperties,
                G.DataWarehousePersonProperties,
            ],
            onChange: noop,
        },
    },
    {
        name: 'Feature flag release condition',
        site: 'FeatureFlagReleaseConditions.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            hasRowOperator: false,
            sendAllKeyUpdates: true,
            allowRelativeDateOptions: true,
            taxonomicGroupTypes: [G.PersonProperties, G.EventProperties, G.Cohorts],
        },
    },
    {
        name: 'Cohort behavioral criteria',
        site: 'CohortField.tsx',
        entry: 'popover',
        props: {
            groupType: G.Events,
            groupTypes: [G.Events, G.Actions],
            onChange: noop,
            placeholder: 'Choose event or action',
        },
    },
    {
        name: 'Persons scene property filter',
        site: 'PersonPropertyFilters.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            taxonomicGroupTypes: [G.PersonProperties, G.Cohorts, G.HogQLExpression],
        },
    },
    {
        name: 'Web analytics property filter',
        site: 'WebPropertyFilters.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            eventNames: ['$pageview'],
            taxonomicGroupTypes: [G.EventProperties, G.SessionProperties, G.PersonProperties, G.Cohorts],
        },
    },
    {
        name: 'Survey audience filter',
        site: 'SurveyAudienceFilters.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            allowRelativeDateOptions: true,
            buttonText: 'Add audience rule',
            taxonomicGroupTypes: [G.PersonProperties, G.Cohorts],
        },
    },
    {
        name: 'Survey event trigger filter',
        site: 'SurveyEventTrigger.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            eventNames: ['signed up'],
            buttonText: 'Add property filter',
            buttonSize: 'small',
            taxonomicGroupTypes: [G.EventProperties],
        },
    },
    {
        name: 'Hog function event filter',
        site: 'HogFunctionFilters.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            taxonomicGroupTypes: [
                G.EventProperties,
                G.EventMetadata,
                G.PersonProperties,
                G.Cohorts,
                G.Elements,
                G.HogQLExpression,
            ],
        },
    },
    {
        name: 'Feature flag selector',
        site: 'FlagSelector.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [G.FeatureFlags],
            selectFirstItem: true,
            onChange: noop,
        },
    },
    {
        name: 'Single property selector',
        site: 'PropertySelect.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [G.EventProperties],
            onChange: noop,
        },
    },
    {
        name: 'Single event selector',
        site: 'EventSelect.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [G.Events],
            onChange: noop,
        },
    },
    {
        name: 'Replay pinned properties',
        site: 'PlayerSidebarEditPinnedPropertiesPopover.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [G.SessionProperties, G.PersonProperties],
            onChange: noop,
        },
    },
    {
        name: 'Error tracking breakdowns',
        site: 'error_tracking/.../Breakdowns/BreakdownsSearchBar.tsx',
        entry: 'filter',
        props: {
            taxonomicGroupTypes: [G.EventProperties, G.PersonProperties],
            onChange: noop,
        },
    },
    {
        name: 'AI observability filters',
        site: 'ai_observability/.../AIObservabilityScene.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            taxonomicGroupTypes: [G.EventProperties, G.PersonProperties, G.Cohorts, G.HogQLExpression],
        },
    },
    {
        name: 'AI observability evaluation triggers',
        site: 'ai_observability/.../evaluations/EvaluationTriggers.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            taxonomicGroupTypes: [G.EventProperties, G.EventMetadata, G.PersonProperties],
        },
    },
    {
        name: 'Error tracking config rule (grouping / assignment / suppression)',
        site: 'error_tracking/.../rules/RuleModal.tsx',
        entry: 'properties',
        props: {
            onChange: noop,
            taxonomicGroupTypes: [G.EventProperties],
        },
    },
    {
        name: 'Logs filter bar',
        site: 'logs/.../LogsViewer/Filters/FilterGroup.tsx',
        entry: 'search',
        props: {
            taxonomicGroupTypes: [G.Logs, G.LogResourceAttributes, G.LogAttributes],
        },
    },
    {
        name: 'Error tracking issue filters',
        site: 'error_tracking/.../IssueFilters/FilterGroup.tsx',
        entry: 'search',
        props: {
            taxonomicGroupTypes: [
                G.ErrorTrackingProperties,
                G.ErrorTrackingIssues,
                G.EventProperties,
                G.PersonProperties,
                G.Cohorts,
                G.HogQLExpression,
            ],
        },
    },
    {
        name: 'Session replay filter bar',
        site: 'session-recordings/filters/RecordingsUniversalFiltersEmbed.tsx',
        entry: 'universal',
        props: {
            taxonomicGroupTypes: [
                G.Replay,
                G.ReplaySavedFilters,
                G.Events,
                G.EventProperties,
                G.Actions,
                G.Cohorts,
                G.EventFeatureFlags,
                G.PersonProperties,
                G.SessionProperties,
                G.HogQLExpression,
            ],
        },
    },
]

function formatValue(value: unknown): string {
    if (typeof value === 'function') {
        return '(fn)'
    }
    if (Array.isArray(value)) {
        return `[${value.join(', ')}]`
    }
    if (value && typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

/** Props minus the ones that don't distinguish one call site from another. */
function formatUsageProps(usage: Usage): string {
    const lines: string[] = []
    for (const [key, value] of Object.entries(usage.props)) {
        if (key === 'onChange') {
            continue
        }
        lines.push(`${key}: ${formatValue(value)}`)
    }
    return lines.join('\n') || '(no distinguishing props)'
}

/**
 * The unique presentations the family collapses to. Many call sites share one —
 * what varies between them is mostly `taxonomicGroupTypes`, listed per site
 * below each variant so the duplication (and the simplification opportunity) is
 * visible at a glance.
 */
const VARIANTS: { key: string; label: string; blurb: string }[] = [
    {
        key: 'filter',
        label: 'TaxonomicFilter — inline picker',
        blurb: 'Raw picker, hosted inside an already-open dropdown. No resting trigger.',
    },
    {
        key: 'popover',
        label: 'TaxonomicPopover — button trigger',
        blurb: 'Generic popover wrapper; resting state is a button.',
    },
    {
        key: 'properties:button',
        label: 'PropertyFilters — button trigger',
        blurb: 'Property-filter rows; the add control is a button.',
    },
    {
        key: 'properties:input',
        label: 'PropertyFilters — input trigger',
        blurb: 'Replay-style input add control (triggerVariant: input).',
    },
    {
        key: 'universal',
        label: 'UniversalFilters — add-filter pills',
        blurb: 'Standard UniversalFilters flow: AND/OR groups + an add-filter pill button. Used by session replay.',
    },
    {
        key: 'search',
        label: 'Search bar — taxonomic primitives',
        blurb: 'Bespoke per-product search box (TaxonomicFilterSearchInput + InfiniteSelectResults) with inline pills. Logs and error tracking each hand-rolled their own.',
    },
]

function variantKey(usage: Usage): string {
    if (usage.entry === 'properties') {
        return `properties:${usage.props.triggerVariant ?? 'button'}`
    }
    return usage.entry
}

const STORY_TITLE: Record<string, string> = {
    'rebuild-menu': 'rebuild menu on (only the wrapper entry points change)',
    'legacy-pill': 'legacy · category dropdown = pill',
    'legacy-control': 'legacy · category dropdown = control',
}

/**
 * The surface a given variant actually renders on a given story. The rebuild
 * flag only swaps the two wrapper entry points, so a raw `TaxonomicFilter`
 * stays on the legacy UI even on the rebuild story — this label makes that
 * explicit per cell instead of letting the story title imply otherwise.
 */
function surfaceFor(key: string, story: string): string {
    // Only the two rebuild wrappers (TaxonomicPopover, TaxonomicPropertyFilter)
    // get the rebuild menu. Raw TaxonomicFilter and UniversalFilters never do.
    const getsRebuild = key === 'popover' || key.startsWith('properties')
    if (getsRebuild && story === 'rebuild-menu') {
        return 'rebuild menu'
    }
    return story === 'legacy-pill' ? 'legacy · pill' : 'legacy · control'
}

function UsagePreview({ usage, storyKey }: { usage: Usage; storyKey: string }): JSX.Element {
    // Raw TaxonomicFilter has no resting state — it IS the open panel, and it
    // autofocuses its search input on mount. Mounting ~8 of those at once made
    // the page jump on load and fight over focus, so reveal them one at a time
    // on click. The wrapper entries already render a compact resting trigger.
    const [open, setOpen] = useState(false)

    if (usage.entry === 'filter') {
        return (
            <>
                <LemonButton type="secondary" size="small" onClick={() => setOpen((v) => !v)}>
                    {open ? 'Hide picker' : 'Show picker'}
                </LemonButton>
                {open && (
                    <div className="border rounded bg-surface-primary w-full max-w-md mt-2">
                        <TaxonomicFilter {...usage.props} taxonomicFilterLogicKey={storyKey} />
                    </div>
                )}
            </>
        )
    }
    if (usage.entry === 'popover') {
        return <TaxonomicPopover {...usage.props} />
    }
    if (usage.entry === 'universal') {
        return (
            <UniversalFilters
                rootKey={storyKey}
                group={DEFAULT_UNIVERSAL_GROUP_FILTER}
                taxonomicGroupTypes={usage.props.taxonomicGroupTypes}
                onChange={noop}
            >
                <UniversalFilterGroupBody />
            </UniversalFilters>
        )
    }
    if (usage.entry === 'search') {
        return <SearchBarPreview taxonomicGroupTypes={usage.props.taxonomicGroupTypes} storyKey={storyKey} />
    }
    // Render inline so the taxonomic trigger itself shows (button vs input) — the
    // popover mode would only show the generic "+ Filter" row button, which is
    // identical across variants and hides the part we want to compare.
    return <PropertyFilters {...usage.props} pageKey={storyKey} disablePopover />
}

/**
 * The bespoke search-bar presentation logs and error tracking build by hand from
 * taxonomic primitives. The real components wire it to product logics; here we
 * render just the resting search input so its distinct shape (a search box, not
 * pill buttons) is visible.
 */
function SearchBarPreview({
    taxonomicGroupTypes,
    storyKey,
}: {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    storyKey: string
}): JSX.Element {
    const searchInputRef = useRef<HTMLInputElement | null>(null)
    return (
        <BindLogic
            logic={taxonomicFilterLogic}
            props={{ taxonomicFilterLogicKey: storyKey, taxonomicGroupTypes, onChange: noop }}
        >
            <TaxonomicFilterSearchInput
                searchInputRef={searchInputRef}
                onClose={noop}
                onChange={noop}
                autoFocus={false}
                fullWidth
                size="small"
                placeholder="Add a filter or search..."
            />
        </BindLogic>
    )
}

/** Minimal UniversalFilters body — renders existing values and the add-filter trigger. */
function UniversalFilterGroupBody(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="flex items-center gap-2 flex-wrap">
            {filterGroup.values.map((filterOrGroup, index) =>
                isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <UniversalFilterGroupBody />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                    />
                )
            )}
            <UniversalFilters.AddFilterButton />
        </div>
    )
}

function Gallery({ variant }: { variant: string }): JSX.Element {
    useMountedLogic(actionsModel)
    useMountedLogic(cohortsModel)

    // The rebuild menu is gated by both the flag (set per story) and this
    // persisted preference. The preference is a real-user escape hatch back to
    // the classic UI; a fixture should always show the rebuild when flagged in,
    // regardless of whatever a dev left in their Storybook localStorage.
    const { setUseNewMenu } = useActions(taxonomicMenuPreferenceLogic)
    useOnMountEffect(() => setUseNewMenu(true))

    return (
        <div className="p-4">
            <h1 className="text-xl font-bold mb-2">Taxonomic filter gallery — {STORY_TITLE[variant] ?? variant}</h1>
            <p className="text-sm text-secondary mb-4 max-w-3xl">
                The taxonomic-filter family collapses to a handful of unique presentations; most call sites just pass a
                different <code>taxonomicGroupTypes</code> to the same one. Each cell renders one variant and lists the
                call sites that use it (with the props that differ), so the duplication — and where it could be
                simplified — is visible. The badge on each cell is the surface it actually renders: the rebuild flag
                only swaps the two wrapper entry points, so raw <code>TaxonomicFilter</code> stays on the legacy UI even
                on the rebuild story. Raw <code>TaxonomicFilter</code> has no resting state, so it reveals on "Show
                picker".
            </p>
            <div className="grid grid-cols-1 xl:grid-cols-2 border-l border-t">
                {VARIANTS.map((v) => {
                    const usages = USAGES.filter((usage) => variantKey(usage) === v.key)
                    if (usages.length === 0) {
                        return null
                    }
                    const storyKey = `gallery-${variant}-${v.key}`
                    return (
                        <div key={v.key} className="border-r border-b p-4 flex flex-col gap-3 min-w-0">
                            <div>
                                <div className="flex items-center gap-2">
                                    <h1 className="text-base font-bold">{v.label}</h1>
                                    <span className="text-2xs uppercase tracking-wide px-1.5 py-0.5 rounded bg-surface-secondary text-secondary whitespace-nowrap">
                                        {surfaceFor(v.key, variant)}
                                    </span>
                                </div>
                                <p className="text-xs text-secondary">{v.blurb}</p>
                            </div>
                            <div className="min-w-0">
                                <UsagePreview usage={usages[0]} storyKey={storyKey} />
                            </div>
                            <div>
                                <div className="text-xs font-semibold text-secondary mb-1">
                                    Used in {usages.length} place{usages.length === 1 ? '' : 's'}:
                                </div>
                                <div className="flex flex-col gap-2">
                                    {usages.map((usage) => (
                                        <div key={usage.site} className="text-xs">
                                            <div className="font-semibold">
                                                {usage.name}{' '}
                                                <span className="font-normal text-secondary">— {usage.site}</span>
                                            </div>
                                            <pre className="bg-surface-secondary p-2 rounded whitespace-pre-wrap break-words">
                                                {formatUsageProps(usage)}
                                            </pre>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

const meta: Meta = {
    title: 'Filters/Taxonomic Filter Gallery',
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        layout: 'fullscreen',
        docs: {
            description: {
                component:
                    'A catalogue of every distinct taxonomic-filter usage across the app, repeated for each live variant, to drive simplification.',
            },
        },
    },
    // Exploration gallery: too many live filters to snapshot reliably, so kept out of visual regression.
    tags: ['test-skip'],
}
export default meta
type Story = StoryObj

export const RebuildMenu: Story = {
    render: () => <Gallery variant="rebuild-menu" />,
    parameters: { featureFlags: { [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true } },
}

export const LegacyPill: Story = {
    render: () => <Gallery variant="legacy-pill" />,
    parameters: { featureFlags: { [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: 'pill' } },
}

export const LegacyControl: Story = {
    render: () => <Gallery variant="legacy-control" />,
    parameters: { featureFlags: { [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: 'control' } },
}
