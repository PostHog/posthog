import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../../generated/api'
import { IMPERSONATE_COLUMN, MEMBERSHIP_COLUMN, accountUsersTableLogic } from './accountUsersTableLogic'

describe('accountUsersTableLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        [
            'adds the staff column to a person select',
            ['properties.email'],
            ['properties.email', IMPERSONATE_COLUMN, MEMBERSHIP_COLUMN],
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
            expect(logic.values.query.hiddenColumns).toContain(MEMBERSHIP_COLUMN)
            expect(logic.values.exportQuery?.hiddenColumns ?? []).not.toContain(MEMBERSHIP_COLUMN)
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
    it('enriches only after table results arrive and keeps failures out of the table', async () => {
        const personId = '00000000-0000-0000-0000-000000000001'
        const membership = {
            person_id: personId,
            accounts: [
                { id: 'current-account', name: 'Current account' },
                { id: 'other-account', name: 'Other account' },
            ],
        }
        const request = jest.spyOn(generatedApi, 'accountsPersonsMembershipsCreate').mockResolvedValue([membership])
        const logic = accountUsersTableLogic({ accountId: 'current-account' })
        logic.mount()
        expect(request).not.toHaveBeenCalled()
        const node = dataNodeLogic({
            key: 'account-users-current-account-default',
            query: logic.values.query.source,
            doNotLoad: true,
        })
        node.mount()
        const response: HogQLQueryResponse = {
            results: [[personId]],
            columns: [MEMBERSHIP_COLUMN],
            types: [],
            hasMore: false,
        }
        await expectLogic(logic, () => node.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(logic.values.memberships).toEqual({ [personId]: membership })
        request.mockRejectedValueOnce(new Error('Enrichment unavailable'))
        await expectLogic(logic, () => node.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(logic.values.memberships).toBeNull()
        expect(node.values.response).toEqual(response)
        node.unmount()
        logic.unmount()
        request.mockRestore()
    })
    it('enriches only new people on the next page and preserves existing memberships', async () => {
        const firstPersonId = '00000000-0000-0000-0000-000000000001'
        const secondPersonId = '00000000-0000-0000-0000-000000000002'
        const first = { person_id: firstPersonId, accounts: [{ id: 'current-account', name: 'Current account' }] }
        const second = { person_id: secondPersonId, accounts: [] }
        const request = jest
            .spyOn(generatedApi, 'accountsPersonsMembershipsCreate')
            .mockResolvedValueOnce([first])
            .mockResolvedValueOnce([second])
        const logic = accountUsersTableLogic({ accountId: 'current-account' })
        logic.mount()
        const node = dataNodeLogic({
            key: 'account-users-current-account-default',
            query: logic.values.query.source,
            doNotLoad: true,
        })
        node.mount()
        const response: HogQLQueryResponse = {
            results: [[firstPersonId]],
            columns: [MEMBERSHIP_COLUMN],
            types: [],
            hasMore: true,
        }
        await expectLogic(logic, () => node.actions.loadDataSuccess(response)).toFinishAllListeners()
        await expectLogic(logic, () =>
            node.actions.loadNextDataSuccess({ ...response, results: [[firstPersonId], [secondPersonId]] })
        ).toFinishAllListeners()
        expect(request).toHaveBeenCalledTimes(2)
        expect(request.mock.calls[1][2]).toEqual({ person_ids: [secondPersonId] })
        expect(logic.values.memberships).toEqual({ [firstPersonId]: first, [secondPersonId]: second })
        await expectLogic(logic, () =>
            node.actions.loadNextDataSuccess({ ...response, results: [[firstPersonId], [secondPersonId]] })
        ).toFinishAllListeners()
        expect(request).toHaveBeenCalledTimes(2)
        node.unmount()
        logic.unmount()
        request.mockRestore()
    })
})
