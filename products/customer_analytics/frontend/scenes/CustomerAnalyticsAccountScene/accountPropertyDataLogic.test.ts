import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsRetrieve } from '../../generated/api'
import type { AccountApi } from '../../generated/api.schemas'
import { accountPropertyDataLogic } from './accountPropertyDataLogic'
import { accountPropertyUpdatesLogic } from './accountPropertyUpdatesLogic'

jest.mock('../../generated/api', () => ({ accountsRetrieve: jest.fn() }))

const PROJECT_ID = 1
const ACCOUNT_ID = '11111111-1111-4111-8111-111111111111'
const account: AccountApi = {
    id: ACCOUNT_ID,
    name: 'Example account',
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    properties: { website_domain: 'example.com' },
}
const mockRetrieve = jest.mocked(accountsRetrieve)

describe('accountPropertyDataLogic', () => {
    let logic: ReturnType<typeof accountPropertyDataLogic.build>

    beforeEach(() => {
        initKeaTests(false)
        mockRetrieve.mockReset().mockResolvedValue(account)
        logic = accountPropertyDataLogic({ projectId: PROJECT_ID, accountId: ACCOUNT_ID })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('keeps a saved value when an earlier account read finishes', async () => {
        let resolveRead!: (value: AccountApi) => void
        mockRetrieve.mockReturnValueOnce(new Promise<AccountApi>((resolve) => (resolveRead = resolve)))
        logic.actions.loadAccount()
        try {
            await waitFor(() => expect(mockRetrieve).toHaveBeenCalledTimes(1))
            accountPropertyUpdatesLogic.actions.accountUpdated(PROJECT_ID, {
                ...account,
                properties: { website_domain: 'saved.example.com' },
            })
        } finally {
            resolveRead(account)
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.account?.properties?.website_domain).toBe('saved.example.com')
    })

    it.each([
        { label: 'project', projectId: PROJECT_ID + 1, accountId: ACCOUNT_ID },
        { label: 'account', projectId: PROJECT_ID, accountId: 'other-account' },
    ])('ignores updates for another $label', async ({ projectId, accountId }) => {
        await expectLogic(logic, () => logic.actions.loadAccount()).toFinishAllListeners()
        accountPropertyUpdatesLogic.actions.accountUpdated(projectId, {
            ...account,
            id: accountId,
            name: 'Other account',
        })
        expect(logic.values.account).toEqual(account)
    })
})
