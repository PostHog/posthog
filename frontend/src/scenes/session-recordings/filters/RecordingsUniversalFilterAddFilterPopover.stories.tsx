import type { Meta, StoryObj } from '@storybook/react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { userEvent, waitFor, within } from 'storybook/test'

import { RecordingsUniversalFilterAddFilterPopover } from './RecordingsUniversalFiltersEmbed'

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
]

const EMPTY_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

const meta: Meta = {
    title: 'Replay/Filters/Add filter popover',
    decorators: [taxonomicFilterMocksDecorator],
    render: () => (
        <div className="p-4 w-160">
            <UniversalFilters
                rootKey="replay-add-filter-story"
                group={EMPTY_GROUP}
                onChange={() => {}}
                taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
            >
                <RecordingsUniversalFilterAddFilterPopover taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES} />
            </UniversalFilters>
        </div>
    ),
}
export default meta
type Story = StoryObj

export const Closed: Story = {}

export const Open: Story = {
    play: async ({ canvasElement }) => {
        const input = await waitFor(() => {
            const element = canvasElement.querySelector<HTMLInputElement>(
                '[data-attr="replay-filters-add-filter-input"]'
            )
            if (!element) {
                throw new Error('search input not rendered yet')
            }
            return element
        })
        await userEvent.click(input)
        await within(document.body).findByTestId('taxonomic-category-dropdown-item-events')
    },
}
