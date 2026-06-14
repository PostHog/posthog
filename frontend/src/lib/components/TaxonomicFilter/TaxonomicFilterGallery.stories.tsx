import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { ComponentProps, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicMenuPreferenceLogic } from 'lib/components/TaxonomicPopover/taxonomicMenuPreferenceLogic'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'

const noop = (): void => {}

type FilterUsage = { entry: 'filter'; props: Omit<ComponentProps<typeof TaxonomicFilter>, 'taxonomicFilterLogicKey'> }
type PopoverUsage = { entry: 'popover'; props: ComponentProps<typeof TaxonomicPopover> }
type PropertiesUsage = { entry: 'properties'; props: Omit<ComponentProps<typeof PropertyFilters>, 'pageKey'> }

/** One catalogued taxonomic-filter usage: a real scene's entry component + the props it passes. */
type Usage = { name: string; site: string } & (FilterUsage | PopoverUsage | PropertiesUsage)

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
    const isWrapper = key !== 'filter'
    if (isWrapper && story === 'rebuild-menu') {
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
    // Render inline so the taxonomic trigger itself shows (button vs input) — the
    // popover mode would only show the generic "+ Filter" row button, which is
    // identical across variants and hides the part we want to compare.
    return <PropertyFilters {...usage.props} pageKey={storyKey} disablePopover />
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
