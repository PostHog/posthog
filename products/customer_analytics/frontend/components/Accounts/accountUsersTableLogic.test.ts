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

    it.each([
        [
            'adds the staff column to a person select',
            ['properties.email'],
            ['properties.email', IMPERSONATE_COLUMN],
            { select: ['properties.email'] },
        ],
        ['keeps an aggregate select grouped', ['count()'], ['count()'], undefined],
    ])(
        '%s, queries the current account and saves and exports without it',
        async (_, select, expectedSelect, expectedExportSource) => {
            userLogic.mount()
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: true })
            const onConfigChange = jest.fn()
            const savedOnAnotherAccount: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    select,
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
                select: expectedSelect,
                source: { kind: NodeKind.AccountUsersQuery, accountId: 'current-account' },
            })
            expect(logic.values.exportQuery?.source).toEqual(
                expectedExportSource && expect.objectContaining(expectedExportSource)
            )

            await expectLogic(logic, () => logic.actions.setQuery(logic.values.query)).toFinishAllListeners()

            expect(onConfigChange).toHaveBeenCalledWith({
                query: {
                    kind: NodeKind.DataTableNode,
                    source: { kind: NodeKind.ActorsQuery, select },
                },
            })
        }
    )
})
