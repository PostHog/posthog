import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { IMPERSONATE_COLUMN, accountUsersTableLogic } from './accountUsersTableLogic'

describe('accountUsersTableLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('queries the current account and saves the table without an account or the staff column', async () => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: true })
        const onConfigChange = jest.fn()
        const savedOnAnotherAccount: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.ActorsQuery,
                select: ['properties.email'],
                source: { kind: NodeKind.AccountUsersQuery, accountId: 'other-account' },
            },
        }
        const logic = accountUsersTableLogic({
            accountId: 'current-account',
            initialConfig: { query: savedOnAnotherAccount },
            onConfigChange,
        })
        logic.mount()

        expect(logic.values.query.source).toMatchObject({
            select: ['properties.email', IMPERSONATE_COLUMN],
            source: { kind: NodeKind.AccountUsersQuery, accountId: 'current-account' },
        })

        await expectLogic(logic, () => logic.actions.setQuery(logic.values.query)).toFinishAllListeners()

        expect(onConfigChange).toHaveBeenCalledWith({
            query: {
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.ActorsQuery, select: ['properties.email'] },
            },
        })
    })
})
