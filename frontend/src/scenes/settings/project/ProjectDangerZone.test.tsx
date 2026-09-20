import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType } from '~/types'

import { DeleteProjectModal } from './ProjectDangerZone'

const product = (overrides: Partial<BillingProductV2Type>): BillingProductV2Type => ({
    ...billingJson.products[0],
    usage_key: 'events',
    percentage_usage: 0.5,
    ...overrides,
})

const loadBilling = (products: BillingProductV2Type[]): void => {
    billingLogic.actions.loadBillingSuccess({ ...billingJson, products } as BillingType)
}

describe('<DeleteProjectModal />', () => {
    beforeEach(() => {
        initKeaTests()
        organizationLogic.mount()
        projectLogic.mount()
        billingLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess(MOCK_DEFAULT_ORGANIZATION)
        projectLogic.actions.loadCurrentProjectSuccess({ id: 1, name: 'Source Project' } as any)
    })

    afterEach(() => {
        cleanup()
    })

    it('warns that a new project shares the organization limit when usage is over the limit', () => {
        loadBilling([product({ type: 'error_tracking', percentage_usage: 1 })])
        render(<DeleteProjectModal isOpen setIsOpen={() => {}} />)

        expect(screen.getByText(/Your organization has reached a usage limit/)).toBeInTheDocument()
        expect(screen.getByText('suppression rule')).toBeInTheDocument()
    })

    it('leaves the warning out when no product is over its limit', () => {
        loadBilling([product({ type: 'error_tracking' })])
        render(<DeleteProjectModal isOpen setIsOpen={() => {}} />)

        expect(screen.queryByText(/Your organization has reached a usage limit/)).not.toBeInTheDocument()
    })
})
