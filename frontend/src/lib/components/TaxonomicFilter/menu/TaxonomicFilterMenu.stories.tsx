import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'

import { actionsModel } from '~/models/actionsModel'

import { TaxonomicFilterHeadless } from '../headless'
import { DataWarehousePopoverField, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
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
        docs: {
            description: {
                story: 'DataWarehouse config form rendered standalone so it lands on the DWH interface immediately. Wide table with mixed types (string / integer / decimal / datetime / boolean / lazy_table / view) exercises every column-type filter in the dropdowns plus the linked-tables hint in the HogQL fallback. Tabs are configured to mirror the funnel popover (Aggregation target / Timestamp / Unique ID).',
            },
        },
    },
}
