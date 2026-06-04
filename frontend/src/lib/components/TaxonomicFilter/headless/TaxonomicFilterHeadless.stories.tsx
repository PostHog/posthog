import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'

import { actionsModel } from '~/models/actionsModel'

import { __clearTaxonomicResourceCache } from '../hooks/useTaxonomicResource'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue } from '../types'
import { TaxonomicFilterHeadless } from './index'

const meta: Meta = {
    title: 'Filters/Taxonomic Filter (Headless)',
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        docs: {
            description: {
                component:
                    'Headless TaxonomicFilter built on Quill primitives. The compound `<Root>/<Input>/<Categories>/<Panel>` API is opt-in via the `TAXONOMIC_FILTER_MENU_REBUILD` feature flag and replaces the kea-based `<TaxonomicFilter>` once parity is verified.',
            },
        },
    },
    tags: ['autodocs'],
}

export default meta

type Story = StoryObj

interface ContainerArgs {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    initialSearchQuery?: string
    suggestedFiltersLabel?: string
    /** Open on a specific content tab. Stories demonstrating a category's list
     *  pin this so they don't land on the auto-injected Suggested tab. */
    groupType?: TaxonomicFilterGroupType
}

function Container({
    taxonomicGroupTypes,
    initialSearchQuery,
    suggestedFiltersLabel,
    groupType,
}: ContainerArgs): JSX.Element {
    useState(() => {
        __clearTaxonomicResourceCache()
        return null
    })
    useMountedLogic(actionsModel)
    const [lastPick, setLastPick] = useState<{
        group: string
        value: TaxonomicFilterValue | null
        name?: string
    } | null>(null)

    return (
        <div className="flex flex-col gap-3 max-w-xl border rounded p-3 bg-surface-primary">
            <TaxonomicFilterHeadless.Root
                taxonomicGroupTypes={taxonomicGroupTypes}
                groupType={groupType}
                initialSearchQuery={initialSearchQuery}
                suggestedFiltersLabel={suggestedFiltersLabel}
                onChange={(group: TaxonomicFilterGroup, value, item: any) => {
                    setLastPick({ group: group.type, value, name: item?.name })
                }}
            >
                <TaxonomicFilterHeadless.Input />
                <TaxonomicFilterHeadless.Categories className="flex flex-row flex-wrap gap-1" />
                <TaxonomicFilterHeadless.Panel className="max-h-80 overflow-auto" />
            </TaxonomicFilterHeadless.Root>
            {lastPick && (
                <div className="text-xs text-secondary">
                    Selected: <code>{lastPick.group}</code> / <code>{String(lastPick.value)}</code>
                    {lastPick.name ? ` (${lastPick.name})` : ''}
                </div>
            )}
        </div>
    )
}

export const EventsAndActions: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            groupType={TaxonomicFilterGroupType.Events}
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Two tabs: Events + Actions, opened on Events to show the list. Tab strip uses Quill `<Button>`, list uses `<ItemMenuItem>`. (Suggested is auto-injected into the strip but this story pins Events to demonstrate the category list.)',
            },
        },
    },
}

export const Properties: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]}
            groupType={TaxonomicFilterGroupType.EventProperties}
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Property picker — Event + Person properties, opened on Event properties. Uses the same headless API as the Events story.',
            },
        },
    },
}

export const SuggestedFiltersWithRecents: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.SuggestedFilters,
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.EventProperties,
            ]}
            suggestedFiltersLabel="Top picks"
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Demonstrates the auto-injected SuggestedFilters tab + a custom label.',
            },
        },
    },
}

export const SuggestedIsDefaultSurface: Story = {
    render: () => (
        <Container taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties]} />
    ),
    parameters: {
        docs: {
            description: {
                story: 'The caller requests Events + Event properties and does NOT ask for SuggestedFilters — but because more than one content group is requested, the Suggested tab is auto-injected as the first tab and is the default active surface. Single-purpose pickers (one content group) are left untouched.',
            },
        },
    },
}
