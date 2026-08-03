import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyDefinitionType } from '~/types'

import { PropertyKeyInfo } from './PropertyKeyInfo'
import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

describe('PropertyKeyInfo', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/property_definitions/': {
                    count: 1,
                    results: [
                        {
                            id: 'a',
                            name: 'referral_cost_usd',
                            description: 'Cost of the referral in USD',
                            type: PropertyDefinitionType.Event,
                        },
                    ],
                    next: undefined,
                },
            },
        })
        initKeaTests()
        propertyDefinitionsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('gains click affordance once a custom property definition loads from the team', async () => {
        render(
            <Provider>
                <PropertyKeyInfo value="referral_cost_usd" type={TaxonomicFilterGroupType.EventProperties} />
            </Provider>
        )

        // Before the property definition loads, a custom key has no definition to show yet.
        expect(screen.getByText('referral_cost_usd').closest('.PropertyKeyInfo')).not.toHaveClass('cursor-pointer')

        await waitFor(() =>
            expect(screen.getByText('referral_cost_usd').closest('.PropertyKeyInfo')).toHaveClass('cursor-pointer')
        )
    })

    it('never gains click affordance for a key with no core or custom definition', async () => {
        render(
            <Provider>
                <PropertyKeyInfo value="totally_unknown_property" type={TaxonomicFilterGroupType.EventProperties} />
            </Provider>
        )

        await waitFor(() =>
            expect(propertyDefinitionsModel.values.propertyDefinitionStorage).toHaveProperty(
                'event/totally_unknown_property'
            )
        )
        expect(screen.getByText('totally_unknown_property').closest('.PropertyKeyInfo')).not.toHaveClass(
            'cursor-pointer'
        )
    })
})
