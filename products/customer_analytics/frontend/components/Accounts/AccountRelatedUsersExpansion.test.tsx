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

    it('opens a dev EU member in the current admin', async () => {
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        jest.spyOn(api, 'query').mockResolvedValue({
            results: [[42, 'membership-1', 'Alex', 'Mercer', 'alex+eu@example.com', 'distinct-1']],
        } as HogQLQueryResponse)

        render(
            <Provider>
                <AccountRelatedUsersExpansion externalId="organization-1" />
            </Provider>
        )

        const impersonateButton = await screen.findByText('Impersonate')
        expect(impersonateButton.closest('a')).toHaveAttribute('href', 'http://localhost/admin/posthog/user/42/change/')
    })
})
