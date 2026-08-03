import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { PropertyKeyInfo } from './PropertyKeyInfo'
import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

describe('PropertyKeyInfo', () => {
    afterEach(() => {
        cleanup()
    })

    it('gains click affordance when a caller-supplied custom definition is present', () => {
        render(
            <PropertyKeyInfo
                value="referral_cost_usd"
                type={TaxonomicFilterGroupType.EventProperties}
                customDefinition={{ label: 'referral_cost_usd', description: 'Cost of the referral in USD' }}
            />
        )

        expect(screen.getByText('referral_cost_usd').closest('.PropertyKeyInfo')).toHaveClass('cursor-pointer')
    })

    it('never gains click affordance for a key with no core or custom definition', () => {
        render(<PropertyKeyInfo value="totally_unknown_property" type={TaxonomicFilterGroupType.EventProperties} />)

        expect(screen.getByText('totally_unknown_property').closest('.PropertyKeyInfo')).not.toHaveClass(
            'cursor-pointer'
        )
    })
})
