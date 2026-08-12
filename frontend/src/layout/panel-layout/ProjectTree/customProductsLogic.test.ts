import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { UserProductListItem, UserProductListReason } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { customProductsLogic } from './customProductsLogic'

const serverRow = (productPath: string): UserProductListItem => ({
    id: `id-${productPath}`,
    product_path: productPath,
    enabled: true,
    reason: UserProductListReason.PRODUCT_INTENT,
    reason_text: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('customProductsLogic', () => {
    let logic: ReturnType<typeof customProductsLogic.build>
    let listCalls: number
    let serverPaths: string[]
    let failBulkUpdate: boolean

    beforeEach(() => {
        listCalls = 0
        serverPaths = []
        failBulkUpdate = false
        useMocks({
            get: {
                '/api/environments/:team_id/user_product_list/': () => {
                    listCalls += 1
                    return [200, { results: serverPaths.map(serverRow) }]
                },
            },
            patch: {
                '/api/environments/:team_id/user_product_list/bulk_update/': () =>
                    failBulkUpdate ? [400, { detail: 'nope' }] : [200, { results: [] }],
            },
        })
        initKeaTests()
        logic = customProductsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps a toggle made while an earlier save was in flight', async () => {
        // The server still only knows about tool A. A refetch on A's success would answer with
        // just A and wipe B off the screen, which is what the user notices.
        serverPaths = ['a']

        await expectLogic(logic, () => {
            logic.actions.setToolEnabled('a', true)
            logic.actions.setToolEnabled('b', true)
        }).toFinishAllListeners()

        expect(logic.values.enabledToolPaths).toEqual(new Set(['a', 'b']))
    })

    it('does not refetch when a save succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.setToolEnabled('a', true)
        }).toFinishAllListeners()

        expect(listCalls).toBe(0)
    })

    it('refetches to revert the optimistic row when a save fails', async () => {
        failBulkUpdate = true
        serverPaths = []

        await expectLogic(logic, () => {
            logic.actions.setToolEnabled('a', true)
        }).toFinishAllListeners()

        expect(listCalls).toBe(1)
        expect(logic.values.enabledToolPaths).toEqual(new Set())
    })
})
