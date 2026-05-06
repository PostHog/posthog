import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'

import { actionsModel } from '~/models/actionsModel'

import { TaxonomicFilterHeadless } from '../headless'
import { TaxonomicFilterGroupType } from '../types'
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
