import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { tagsModel } from '~/models/tagsModel'
import { initKeaTests } from '~/test/init'

import { objectKindLabel, otherObjectCount, supportTagsLogic, ticketCount } from './supportTagsLogic'

const BILLING_TAG = {
    id: '018f0000-0000-7000-8000-000000000001',
    name: 'billing',
    counts_by_type: { ticket: 4, dashboard: 2 },
    total_count: 6,
}

const BLING_TAG = {
    id: '018f0000-0000-7000-8000-000000000002',
    name: 'bling',
    counts_by_type: { ticket: 1 },
    total_count: 1,
}

describe('supportTagsLogic', () => {
    let logic: ReturnType<typeof supportTagsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/tags/usage/': { count: 2, results: [BILLING_TAG, BLING_TAG] },
                '/api/projects/:team_id/tags/': [],
            },
            patch: {
                '/api/projects/:team_id/tags/:id/': { ...BILLING_TAG, name: 'billing & plans' },
            },
            post: {
                '/api/projects/:team_id/tags/:id/merge/': { id: BILLING_TAG.id, name: 'billing', moved_count: 1 },
            },
            delete: {
                '/api/projects/:team_id/tags/:id/': { status: 204 },
            },
        })
        initKeaTests()
        logic = supportTagsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['tags on tickets only', BLING_TAG, 1, 0],
        ['tags shared with another kind of object', BILLING_TAG, 4, 2],
    ])('%s reports its ticket and non-ticket counts', (_label, tag, tickets, others) => {
        expect(ticketCount(tag)).toBe(tickets)
        expect(otherObjectCount(tag)).toBe(others)
    })

    it.each([
        ['dashboard', 1, '1 dashboard'],
        ['dashboard', 3, '3 dashboards'],
        ['feature_flag', 2, '2 feature flags'],
    ])('labels %s objects', (kind, count, expected) => {
        expect(objectKindLabel(kind, count)).toBe(expected)
    })

    it('renames a tag in place and refreshes the shared tag list', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.renameTag({ tag: BILLING_TAG, name: 'billing & plans' })
        })
            .toDispatchActions([tagsModel.actionTypes.refreshTags, 'renameTagSuccess'])
            .toMatchValues({ tags: [{ ...BILLING_TAG, name: 'billing & plans' }, BLING_TAG] })
    })

    it('drops a deleted tag from the list', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.deleteTag({ tag: BILLING_TAG })
        })
            .toDispatchActions(['deleteTagSuccess'])
            .toMatchValues({ tags: [BLING_TAG] })
    })

    it('reloads the list after a merge, because a merge moves counts between rows', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.mergeTag({ tag: BLING_TAG, intoId: BILLING_TAG.id })
        }).toDispatchActions(['mergeTagSuccess', 'loadTags'])
    })
})
