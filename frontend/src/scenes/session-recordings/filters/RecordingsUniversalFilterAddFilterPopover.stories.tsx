import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { userEvent } from 'storybook/test'

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

function findByDataAttr(container: ParentNode, dataAttr: string): Promise<HTMLElement> {
    return waitFor(() => {
        const element = container.querySelector<HTMLElement>(`[data-attr="${dataAttr}"]`)
        if (!element) {
            throw new Error(`${dataAttr} not rendered yet`)
        }
        return element
    })
}

export const Open: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await findByDataAttr(canvasElement, 'replay-filters-add-filter-input'))
        await userEvent.click(await findByDataAttr(document.body, 'taxonomic-category-dropdown-trigger-pill'))
        await findByDataAttr(document.body, 'taxonomic-category-dropdown-item-events')
    },
}
