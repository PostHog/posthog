import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType } from '~/types'

import { UsageLimitDeletionNotice } from './UsageLimitDeletionNotice'

const product = (overrides: Partial<BillingProductV2Type>): BillingProductV2Type => ({
    ...billingJson.products[0],
    usage_key: 'events',
    percentage_usage: 0.5,
    ...overrides,
})

const billingWith = (products: BillingProductV2Type[]): BillingType => ({ ...billingJson, products }) as BillingType

describe('<UsageLimitDeletionNotice />', () => {
    let billingState: BillingType

    beforeEach(() => {
        billingState = billingWith([])
        useMocks({ get: { '/api/billing': () => [200, billingState] } })
        initKeaTests()
        billingLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('warns that a new project shares the organization limit when usage is over the limit', () => {
        billingLogic.actions.loadBillingSuccess(billingWith([product({ type: 'error_tracking', percentage_usage: 1 })]))
        render(<UsageLimitDeletionNotice />)

        expect(screen.getByText(/Your organization has reached a usage limit/)).toBeInTheDocument()
        expect(screen.getByText('suppression rule')).toBeInTheDocument()
    })

    it('leaves the warning out when no product is over its limit', () => {
        billingLogic.actions.loadBillingSuccess(billingWith([product({ type: 'error_tracking' })]))
        render(<UsageLimitDeletionNotice />)

        expect(screen.queryByText(/Your organization has reached a usage limit/)).not.toBeInTheDocument()
    })

    it('loads billing itself, so an unloaded billing state does not hide the warning', async () => {
        billingState = billingWith([product({ type: 'session_replay', percentage_usage: 1 })])
        render(<UsageLimitDeletionNotice />)

        expect(await screen.findByText(/Your organization has reached a usage limit/)).toBeInTheDocument()
        expect(screen.queryByText('suppression rule')).not.toBeInTheDocument()
    })
})
