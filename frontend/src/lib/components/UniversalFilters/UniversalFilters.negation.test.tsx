import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { ActionFilter, EntityTypes, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import UniversalFilters from './UniversalFilters'

// Stub the taxonomic picker so the "change event" flow can be exercised without
// pinning taxonomic list internals or mocking its API calls.
jest.mock('../TaxonomicFilter/TaxonomicFilter', () => {
    const React = require('react')
    return {
        TaxonomicFilter: ({ onChange }: { onChange: (group: any, value: any, item: any) => void }): JSX.Element =>
            React.createElement(
                'button',
                { onClick: () => onChange({ type: 'events' }, 'purchase', { name: 'purchase' }) },
                'mock taxonomic option: purchase'
            ),
    }
})

describe('UniversalFilters entity negation', () => {
    const eventFilter: ActionFilter = { id: '$pageview', name: '$pageview', type: EntityTypes.EVENTS, properties: [] }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function renderValue(
        allowEntityNegation: boolean,
        onChange: jest.Mock,
        filter: ActionFilter = eventFilter
    ): HTMLElement {
        const group: UniversalFiltersGroup = { type: FilterLogicalOperator.And, values: [filter] }
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
                        filter={filter}
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

    it.each([[true], [false]])('allowEntityNegation=%s controls the negation toggle', async (allowEntityNegation) => {
        const onChange = jest.fn()
        const container = renderValue(allowEntityNegation, onChange)
        await openChipPopover(container)
        if (allowEntityNegation) {
            await userEvent.click(screen.getByText('Did not perform'))
            expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ negation: true }))
        } else {
            expect(screen.queryByText('Did not perform')).toBeNull()
        }
    })

    it('keeps negation when changing the event', async () => {
        const onChange = jest.fn()
        const container = renderValue(true, onChange, { ...eventFilter, negation: true })
        await openChipPopover(container)
        await userEvent.click(screen.getByText('Change event'))
        await userEvent.click(screen.getByText('mock taxonomic option: purchase'))
        expect(onChange).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'purchase', name: 'purchase', properties: [], negation: true })
        )
    })
})
