import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { TaxonomicFilterGroupType } from '../../TaxonomicFilter/types'
import { PropertyFilters } from '../PropertyFilters'

describe('TaxonomicPropertyFilter flag tooltip', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the flag overview in the tooltip of a flag filter', async () => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/': {
                    count: 1,
                    results: [{ key: 'my-flag', active: true, filters: { groups: [] } }],
                },
            },
        })
        render(
            <Provider>
                <PropertyFilters
                    pageKey="flag-tooltip-test"
                    propertyFilters={[
                        {
                            type: PropertyFilterType.Event,
                            key: '$feature/my-flag',
                            value: 'test',
                            operator: PropertyOperator.Exact,
                        },
                    ]}
                    onChange={jest.fn()}
                    disablePopover
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                />
            </Provider>
        )

        const button = screen.getByLabelText('Feature: my-flag').closest('button')!
        await userEvent.hover(button)

        expect(await screen.findByText('Enabled', {}, { timeout: 3000 })).toBeInTheDocument()
    })
})
