import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'

describe('AccountRelatedUsersExpansion', () => {
    beforeEach(() => {
        initKeaTests()
        jest.restoreAllMocks()
        userLogic.actions.loadUserSuccess({ is_staff: true } as UserType)
    })

    afterEach(() => {
        cleanup()
    })

    it('opens an EU member in EU admin', async () => {
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        jest.spyOn(api, 'query').mockResolvedValue({
            results: [['membership-1', 'Alex', 'Mercer', 'alex+eu@example.com', 'distinct-1']],
        } as HogQLQueryResponse)

        render(
            <Provider>
                <AccountRelatedUsersExpansion externalId="organization-1" />
            </Provider>
        )

        const loginButton = await screen.findByText('Log in as')
        expect(loginButton.closest('a')).toHaveAttribute(
            'href',
            'https://eu.posthog.com/admin/posthog/user/?q=alex%2Beu%40example.com'
        )
    })
})
