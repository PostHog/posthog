import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'

import { actionsModel } from '~/models/actionsModel'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue } from '../types'
import { TaxonomicFilterHeadless } from './index'

const meta: Meta = {
    title: 'Filters/Taxonomic Filter (Headless)',
    decorators: [taxonomicFilterMocksDecorator],
    parameters: {
        docs: {
            description: {
                component:
                    'Headless TaxonomicFilter built on Quill primitives. The compound `<Root>/<Input>/<Categories>/<Panel>` API is opt-in via the `TAXONOMIC_FILTER_HEADLESS` feature flag and replaces the kea-based `<TaxonomicFilter>` once parity is verified.',
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
}

function Container({ taxonomicGroupTypes, initialSearchQuery, suggestedFiltersLabel }: ContainerArgs): JSX.Element {
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
        <Container taxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]} />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Two tabs: Events + Actions. Tab strip uses Quill `<Button>`, list uses `<ItemMenuItem>`.',
            },
        },
    },
}

export const Properties: Story = {
    render: () => (
        <Container
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]}
        />
    ),
    parameters: {
        docs: {
            description: {
                story: 'Property picker — Event + Person properties. Uses the same headless API as the Events story.',
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
