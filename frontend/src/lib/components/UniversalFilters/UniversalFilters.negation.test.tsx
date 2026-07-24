import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { ActionFilter, EntityTypes, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import UniversalFilters from './UniversalFilters'

describe('UniversalFilters entity negation', () => {
    const eventFilter: ActionFilter = { id: '$pageview', name: '$pageview', type: EntityTypes.EVENTS, properties: [] }
    const group: UniversalFiltersGroup = { type: FilterLogicalOperator.And, values: [eventFilter] }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function renderValue(allowEntityNegation: boolean, onChange: jest.Mock): HTMLElement {
        const { container } = render(
            <Provider>
                <UniversalFilters
                    rootKey="negation-test"
                    group={group}
                    onChange={jest.fn()}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                >
                    <UniversalFilters.Value
                        index={0}
                        filter={eventFilter}
                        onChange={onChange}
                        allowEntityNegation={allowEntityNegation}
                    />
                </UniversalFilters>
            </Provider>
        )
        return container
    }

    async function openChipPopover(container: HTMLElement): Promise<void> {
        const chipButton = container.querySelector('.UniversalFilterButton button')
        expect(chipButton).not.toBeNull()
        await userEvent.click(chipButton as Element)
    }

    it('writes negation onto the filter when toggled', async () => {
        const onChange = jest.fn()
        const container = renderValue(true, onChange)
        await openChipPopover(container)
        await userEvent.click(screen.getByText('Did not perform'))
        expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ negation: true }))
    })

    it('does not render the control when negation is not allowed', async () => {
        const container = renderValue(false, jest.fn())
        await openChipPopover(container)
        expect(screen.queryByText('Did not perform')).toBeNull()
    })
})
