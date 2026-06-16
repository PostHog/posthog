import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { FEATURE_FLAGS } from 'lib/constants'

import { actionsModel } from '~/models/actionsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { TaxonomicFilterHeadless } from '../headless'
import { DataWarehousePopoverField, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { MenuFilterCombobox } from './Combobox'
import { MenuFilterDwhConfig } from './DwhFlow'
import { TaxonomicFilterMenu } from './TaxonomicFilterMenu'
import { MenuFilterEntry } from './types'

const meta: Meta = {
    title: 'Filters/Taxonomic Filter (Menu rebuild)',
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        docs: {
            description: {
                component:
                    'Popover-fronted TaxonomicFilter — dropdown menu for shortcuts, combobox with chips + preview pane for browsing, and dedicated panels for DataWarehouse config and HogQL expression editing. Gated in production by the `taxonomic-filter-menu-rebuild` flag.',
            },
        },
    },
    tags: ['autodocs'],
}

export default meta

type Story = StoryObj

interface ContainerProps {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    eventNames?: string[]
    suggestedFiltersLabel?: string
    /** Pre-seeded selection — the trigger label uses it and the menu routes
     *  the initial open straight into the panel that owns it. */
    initialSelected?: MenuFilterEntry | null
    triggerLabel?: string
}

function Container({
    taxonomicGroupTypes,
    eventNames,
    suggestedFiltersLabel,
    initialSelected = null,
    triggerLabel = 'Filter',
}: ContainerProps): JSX.Element {
    useMountedLogic(actionsModel)
    const [selected, setSelected] = useState<MenuFilterEntry | null>(initialSelected)

    return (
        <div className="flex flex-col gap-3 max-w-2xl">
            <TaxonomicFilterHeadless.Root
                bindRootProps={false}
                taxonomicGroupTypes={taxonomicGroupTypes}
                eventNames={eventNames}
                suggestedFiltersLabel={suggestedFiltersLabel}
            >
                <TaxonomicFilterMenu
                    triggerLabel={triggerLabel}
                    selected={selected}
                    onCommit={(entry) => setSelected(entry)}
                />
            </TaxonomicFilterHeadless.Root>
            {selected && (
                <div className="text-xs text-secondary">
                    Selected: <code>{selected.group.type}</code>
                    {' / '}
                    <code>{selected.friendlyLabel ?? selected.name}</code>
                </div>
            )}
        </div>
    )
}

export const EventsAndActions: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            triggerLabel="Pick event or action"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Two-tab combobox. Click the trigger → dropdown menu → "New filter…" → combobox with All / Events / Actions chips.',
            },
        },
    },
}

export const Properties: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.SessionProperties,
                TaxonomicFilterGroupType.EventMetadata,
            ]}
            triggerLabel="Pick property"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Property picker — chips for each property family. The preview pane on the right shows description, type, sent-as, and pin/view actions for the highlighted row.',
            },
        },
    },
}

export const SeriesPlusDataWarehouse: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.DataWarehouse,
                TaxonomicFilterGroupType.HogQLExpression,
                TaxonomicFilterGroupType.EventProperties,
            ]}
            triggerLabel="Pick series source"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Mirrors the ActionFilterRow series picker — Data warehouse tables and HogQL expression appear as separate dropdown-menu entries (with chevrons) so they bypass the chip row and route directly to their dedicated panels.',
            },
        },
    },
}

export const HogQLOnly: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.HogQLExpression]}
            triggerLabel="Write SQL expression"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Dropdown only shows the HogQL entry — clicking it opens the lazy-loaded Monaco editor. ⌘+Enter saves; Esc returns to the menu (and falls through to suggestions / find widgets first).',
            },
        },
    },
}

export const PreSelectedEvent: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            initialSelected={
                {
                    item: { name: '$pageview', id: '$pageview' },
                    group: { type: TaxonomicFilterGroupType.Events },
                    name: '$pageview',
                    friendlyLabel: 'Pageview',
                } as unknown as MenuFilterEntry
            }
            triggerLabel="Pick event"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Trigger pre-seeded with a selection — clicking the trigger jumps straight into the combobox with the matching chip active and the row highlighted + checkmarked + scrolled into view.',
            },
        },
    },
}

export const PreSelectedHogQL: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.HogQLExpression]}
            initialSelected={
                {
                    item: { name: "properties.$browser = 'Chrome'" },
                    group: { type: TaxonomicFilterGroupType.HogQLExpression },
                    name: "properties.$browser = 'Chrome'",
                } as unknown as MenuFilterEntry
            }
            triggerLabel="Pick filter"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Pre-existing HogQL expression — re-opening lands directly on the Monaco editor pre-filled with the saved expression for editing.',
            },
        },
    },
}

// ---- DataWarehouse config story --------------------------------------
// Renders `<MenuFilterDwhConfig>` directly so the DWH interface is the
// initial visible surface — no need to click through the trigger /
// dropdown menu first. Useful as a focused debug surface for layout +
// the DatabaseTablePreview / Tabs / Select / HogQL fallback chrome.

const COMPLEX_DWH_TABLE = {
    name: 'chargebee.customers',
    type: 'data_warehouse',
    fields: {
        id: { name: 'id', type: 'string' },
        mrr: { name: 'mrr', type: 'integer' },
        email: { name: 'email', type: 'string' },
        phone: { name: 'phone', type: 'string' },
        object: { name: 'object', type: 'string' },
        channel: { name: 'channel', type: 'string' },
        first_invoiced_at: { name: 'first_invoiced_at', type: 'datetime' },
        created_at: { name: 'created_at', type: 'datetime' },
        updated_at: { name: 'updated_at', type: 'datetime' },
        ltv: { name: 'ltv', type: 'decimal' },
        is_active: { name: 'is_active', type: 'boolean' },
        metadata: { name: 'metadata', type: 'string' },
        // Linked tables to demo the linked-tables hint in HogQL fallback.
        person_distinct_ids: { name: 'person_distinct_ids', type: 'lazy_table' },
        events: { name: 'events', type: 'view' },
    },
}

const DWH_GROUP: TaxonomicFilterGroup = {
    name: 'Data warehouse tables',
    searchPlaceholder: 'data warehouse tables',
    type: TaxonomicFilterGroupType.DataWarehouse,
    getName: (t: any) => t.name,
    getValue: (t: any) => t.name,
    getPopoverHeader: () => 'Data warehouse table',
} as unknown as TaxonomicFilterGroup

const COMPLEX_DWH_FIELDS: DataWarehousePopoverField[] = [
    {
        key: 'aggregation_target_field',
        label: 'Aggregation target',
        description: 'Used to match people or groups across funnel steps.',
        allowHogQL: true,
    },
    {
        key: 'timestamp_field',
        label: 'Timestamp',
        description: 'Used to order step timing and apply the funnel date range.',
        allowHogQL: true,
    },
    {
        key: 'id_field',
        label: 'Unique ID',
        description: 'Used as the unique row ID to detect duplicate records.',
    },
]

function DwhConfigContainer(): JSX.Element {
    useMountedLogic(actionsModel)
    const [committed, setCommitted] = useState<{ name: string; extras?: Record<string, unknown> } | null>(null)
    return (
        <div className="flex flex-col gap-3 max-w-3xl">
            <TaxonomicFilterHeadless.Root
                bindRootProps={false}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.DataWarehouse,
                ]}
            >
                {/* Fixed-size frame so the DwhFlow lays out as it would
                    inside the popover (h-[400px], w-[720px]) and we can
                    spot-check the chrome / scroll behaviour. */}
                <div className="border rounded overflow-hidden flex flex-col w-[720px] h-[480px] bg-surface-primary">
                    <MenuFilterDwhConfig
                        table={COMPLEX_DWH_TABLE as never}
                        group={DWH_GROUP}
                        dataWarehousePopoverFields={COMPLEX_DWH_FIELDS}
                        onCommit={(entry, extras) => setCommitted({ name: entry.name, extras })}
                        onBack={() => setCommitted(null)}
                    />
                </div>
            </TaxonomicFilterHeadless.Root>
            {committed && (
                <pre className="text-xs text-secondary border rounded p-2 max-w-3xl overflow-auto">
                    {JSON.stringify(committed, null, 2)}
                </pre>
            )}
        </div>
    )
}

export const DataWarehouseConfig: Story = {
    render: () => <DwhConfigContainer />,
    parameters: {
        featureFlags: { [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true },
        testOptions: {
            waitForSelector: '[data-attr="dwh-config-back"]',
            snapshotTargetSelector: '[data-slot="dialog-content"]',
        },
        docs: {
            description: {
                story: 'DataWarehouse config form rendered standalone so it lands on the DWH interface immediately. Wide table with mixed types (string / integer / decimal / datetime / boolean / lazy_table / view) exercises every column-type filter in the dropdowns plus the linked-tables hint in the HogQL fallback. Tabs are configured to mirror the funnel popover (Aggregation target / Timestamp / Unique ID).',
            },
        },
    },
}

// ---- Default "All" surface with recents/pinned --------------------------
// Renders the combobox directly on the `all` scope so the recents-first
// default surface is the initial snapshot (no click-through the dropdown
// menu first). Recents/pinned are synthesized so the order is deterministic.

function recentPinnedEntry(groupType: TaxonomicFilterGroupType, name: string, groupName: string): MenuFilterEntry {
    return {
        item: { name } as never,
        group: {
            type: groupType,
            name: groupName,
            getName: (t: any) => t?.name,
            getValue: (t: any) => t?.name,
        } as unknown as TaxonomicFilterGroup,
        name,
    }
}

function DefaultSurfaceContainer(): JSX.Element {
    useMountedLogic(actionsModel)
    const recentEntries = [
        recentPinnedEntry(TaxonomicFilterGroupType.Events, 'signed up', 'Events'),
        recentPinnedEntry(TaxonomicFilterGroupType.EventProperties, 'plan', 'Event properties'),
    ]
    const pinnedEntries = [recentPinnedEntry(TaxonomicFilterGroupType.EventProperties, 'industry', 'Event properties')]
    return (
        <div className="flex flex-col gap-3 max-w-2xl">
            <TaxonomicFilterHeadless.Root
                bindRootProps={false}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.EventProperties,
                ]}
            >
                <div className="border rounded overflow-hidden flex flex-col w-[720px] h-[480px] bg-surface-primary">
                    <MenuFilterCombobox
                        drillTo="all"
                        recentEntries={recentEntries}
                        pinnedEntries={pinnedEntries}
                        onCommit={() => {}}
                        onBack={() => {}}
                    />
                </div>
            </TaxonomicFilterHeadless.Root>
        </div>
    )
}

export const DefaultSurfaceWithRecents: Story = {
    // Excluded from the snapshot/flake gate: the combobox autofocuses, fetches
    // content lists, and the preview pane loads definition metadata async, so
    // the render isn't pixel-stable across runs. Kept for the Storybook demo;
    // the recents-first behaviour is covered by RTL in Combobox.test.tsx.
    tags: ['test-skip'],
    render: () => <DefaultSurfaceContainer />,
    parameters: {
        docs: {
            description: {
                story: 'The default "All" surface staff land on, brought in line with the pill variant: recents lead, then pinned, then the cross-tab content in fixed (learnable) order. Recent/pinned rows are tagged with their source (e.g. "Events - recent"), and the category dropdown exposes Recent and Pinned alongside the content categories so they stay navigable.',
            },
        },
    },
}

function bareKeyRecentEntries(): MenuFilterEntry[] {
    const group = {
        type: TaxonomicFilterGroupType.EventProperties,
        name: 'Event properties',
        getName: (item: { name?: string }) => item?.name,
        getValue: (item: { name?: string }) => item?.name,
    } as unknown as TaxonomicFilterGroup
    const friendlyLabel = getCoreFilterDefinition('$browser', TaxonomicFilterGroupType.EventProperties)?.label
    const propertyFilter: AnyPropertyFilter = {
        type: PropertyFilterType.Event,
        key: '$browser',
        operator: PropertyOperator.Exact,
        value: 'Chrome',
    }
    const bareKey = { item: { name: '$browser' }, group, name: '$browser', friendlyLabel } as MenuFilterEntry
    const full = {
        item: { name: '$browser' },
        group,
        name: '$browser',
        friendlyLabel,
        recentPropertyFilter: propertyFilter,
        recentLabel: formatPropertyLabel(propertyFilter, {}),
    } as MenuFilterEntry
    return [bareKey, full]
}

function BareKeyRecentsContainer(): JSX.Element {
    useMountedLogic(actionsModel)
    return (
        <TaxonomicFilterHeadless.Root
            bindRootProps={false}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
        >
            <div className="border rounded overflow-hidden flex flex-col w-[720px] h-[420px] bg-surface-primary">
                <MenuFilterCombobox
                    drillTo="recent"
                    drillItems={bareKeyRecentEntries()}
                    title="Recent"
                    onCommit={() => {}}
                    onBack={() => {}}
                />
            </div>
        </TaxonomicFilterHeadless.Root>
    )
}

export const RecentsBareKeyExpansion: Story = {
    render: () => <BareKeyRecentsContainer />,
    parameters: {
        testOptions: { waitForSelector: '[data-slot="menu-filter-preview"]' },
        docs: {
            description: {
                story: "The menu combobox's Recent drill after a complete recent (`Browser = Chrome`) was used. The bare key (`Browser`) leads so a user can jump to the key and pick a fresh value, and the full recent (`Browser = Chrome`) follows.",
            },
        },
    },
}
