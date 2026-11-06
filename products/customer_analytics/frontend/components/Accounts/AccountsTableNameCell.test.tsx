import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { accountsExpansionLogic } from './accountsExpansionLogic'
import { AccountsTableNameCell } from './AccountsTableNameCell'
import { AccountsEvents } from './constants'

const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'

describe('AccountsTableNameCell', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        accountsExpansionLogic.mount()
        jest.spyOn(posthog, 'capture').mockImplementation()
    })

    afterEach(() => {
        cleanup()
        featureFlagLogic.unmount()
        accountsExpansionLogic.unmount()
    })

    it('expands the row instead of navigating when the account scene flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        render(
            <Provider>
                <AccountsTableNameCell accountId={ACCOUNT_ID} name="Test account" viewers={[]} />
            </Provider>
        )

        const link = screen.getByText('Test account')
        expect(fireEvent.click(link)).toBe(false)

        expect(accountsExpansionLogic.values.isAccountExpanded(ACCOUNT_ID)).toBe(true)
        expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.AccountOpened)
    })

    it('keeps modifier-click behavior for the account link', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        render(
            <Provider>
                <AccountsTableNameCell accountId={ACCOUNT_ID} name="Test account" viewers={[]} />
            </Provider>
        )

        fireEvent.click(screen.getByText('Test account'), { metaKey: true })

        expect(accountsExpansionLogic.values.isAccountExpanded(ACCOUNT_ID)).toBe(false)
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it('navigates to the account scene without expanding when the flag is on', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]: true })

        render(
            <Provider>
                <AccountsTableNameCell accountId={ACCOUNT_ID} name="Test account" viewers={[]} />
            </Provider>
        )

        const link = screen.getByText('Test account')
        expect(link.closest('a')?.getAttribute('href')).toMatch(
            new RegExp(`/customer_analytics/accounts/${ACCOUNT_ID}$`)
        )
        fireEvent.click(link)

        expect(router.values.location.pathname).toMatch(new RegExp(`/customer_analytics/accounts/${ACCOUNT_ID}$`))
        expect(accountsExpansionLogic.values.isAccountExpanded(ACCOUNT_ID)).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.AccountOpened)
    })

    it('shows three viewer indicators and names every viewer in the hover label', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        render(
            <Provider>
                <AccountsTableNameCell
                    accountId={ACCOUNT_ID}
                    name="Test account"
                    viewers={[
                        { user_id: 1, display_name: 'Alex Rivera' },
                        { user_id: 2, display_name: 'Morgan Lee' },
                        { user_id: 3, display_name: 'Sam Patel' },
                        { user_id: 4, display_name: 'Jordan Kim' },
                    ]}
                />
            </Provider>
        )

        expect(
            screen.getByLabelText('Alex Rivera, Morgan Lee, Sam Patel, and Jordan Kim are viewing this account')
        ).toBeVisible()
        expect(screen.getByText('+1')).toBeVisible()
    })
})
