import { expectLogic } from 'kea-test-utils'

import { ActorsQuery, DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { accountUsersTableLogic } from './accountUsersTableLogic'

describe('accountUsersTableLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('queries the current account and saves the table without an account', async () => {
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

        expect((logic.values.query.source as ActorsQuery).source).toEqual({
            kind: NodeKind.AccountUsersQuery,
            accountId: 'current-account',
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
