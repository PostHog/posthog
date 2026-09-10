import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'

import { accountsPresenceCreate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'

import { AccountPresence } from './AccountPresence'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsPresenceCreate: jest.fn(),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsPresenceCreate = accountsPresenceCreate as jest.MockedFunction<typeof accountsPresenceCreate>
const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

describe('AccountPresence', () => {
    const logic = customerAnalyticsAccountSceneLogic({ accountId: ACCOUNT_ID })

    beforeEach(() => {
        initKeaTests()
        mockAccountsPresenceCreate.mockResolvedValue([])
        mockAccountsRetrieve.mockResolvedValue({
            id: ACCOUNT_ID,
            name: 'Example account',
            tags: [],
            notebooks: [],
            ignored_at: null,
            created_at: '2026-01-01T00:00:00Z',
            created_by: null,
            updated_at: null,
        })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('shows five avatars and describes overflow viewers', () => {
        logic.actions.loadAccountPresenceSuccess([
            { user_id: 1, display_name: 'Alex Rivera' },
            { user_id: 2, display_name: 'Morgan Lee' },
            { user_id: 3, display_name: 'Sam Patel' },
            { user_id: 4, display_name: 'Jordan Kim' },
            { user_id: 5, display_name: 'Taylor Reed' },
            { user_id: 6, display_name: 'Casey Nguyen' },
        ])

        const { container } = render(
            <BindLogic logic={customerAnalyticsAccountSceneLogic} props={{ accountId: ACCOUNT_ID }}>
                <AccountPresence />
            </BindLogic>
        )

        expect(
            screen.getByLabelText(
                'Alex Rivera, Morgan Lee, Sam Patel, Jordan Kim, Taylor Reed, and 1 more are viewing this account'
            )
        ).toBeInTheDocument()
        expect(container.querySelectorAll('.ProfilePicture')).toHaveLength(5)
        expect(screen.getByText('+1')).toBeInTheDocument()
    })
})
