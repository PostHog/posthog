import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { ComponentProps } from 'react'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { FEATURE_FLAGS } from 'lib/constants'

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

function formatProps(usage: Usage): string {
    const entryName =
        usage.entry === 'filter'
            ? 'TaxonomicFilter'
            : usage.entry === 'popover'
              ? 'TaxonomicPopover'
              : 'PropertyFilters'
    const lines = [`entry: <${entryName}>`, `site: ${usage.site}`]
    for (const [key, value] of Object.entries(usage.props)) {
        lines.push(`${key}: ${formatValue(value)}`)
    }
    return lines.join('\n')
}

function renderEntry(usage: Usage, key: string): JSX.Element {
    if (usage.entry === 'filter') {
        return (
            <div className="border rounded bg-surface-primary w-full max-w-md">
                <TaxonomicFilter {...usage.props} taxonomicFilterLogicKey={key} />
            </div>
        )
    }
    if (usage.entry === 'popover') {
        return <TaxonomicPopover {...usage.props} />
    }
    // Render inline so the taxonomic trigger itself shows (button vs input) — the
    // popover mode would only show the generic "+ Filter" row button, which is
    // identical across variants and hides the part we want to compare.
    return <PropertyFilters {...usage.props} pageKey={key} disablePopover />
}

function Gallery({ variant }: { variant: string }): JSX.Element {
    useMountedLogic(actionsModel)
    useMountedLogic(cohortsModel)

    return (
        <div className="p-4">
            <h1 className="text-xl font-bold mb-2">Taxonomic filter gallery — {variant}</h1>
            <p className="text-sm text-secondary mb-4 max-w-3xl">
                Every distinct taxonomic-filter usage in one place, so we can compare them and start to simplify. Each
                cell lists the entry component and the props that scene passes, then renders it. Raw
                <code> TaxonomicFilter</code> renders its inline panel; <code>PropertyFilters</code> cells are forced
                inline (<code>disablePopover</code>) so the taxonomic trigger itself shows — button vs replay-style
                input; <code>TaxonomicPopover</code> renders its resting trigger (click to open). The rebuild menu only
                replaces the two wrapper entry points, so raw <code>TaxonomicFilter</code> cells stay on the legacy UI
                here.
            </p>
            <div className="grid grid-cols-1 xl:grid-cols-2 border-l border-t">
                {USAGES.map((usage, index) => {
                    const key = `gallery-${variant}-${index}`
                    return (
                        <div key={key} className="border-r border-b p-4 flex flex-col gap-2 min-w-0">
                            <h1 className="text-base font-bold">{usage.name}</h1>
                            <pre className="text-xs bg-surface-secondary p-2 rounded whitespace-pre-wrap break-words">
                                {formatProps(usage)}
                            </pre>
                            <div className="mt-2 min-w-0">{renderEntry(usage, key)}</div>
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
