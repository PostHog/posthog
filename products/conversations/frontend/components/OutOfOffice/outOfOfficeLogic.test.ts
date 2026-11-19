import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { outOfOfficeLogic } from './outOfOfficeLogic'

const entry = (user: typeof MOCK_DEFAULT_BASIC_USER): Record<string, unknown> => ({
    id: `ooo-${user.id}`,
    user,
    since: '2026-11-17T09:00:00Z',
})

describe('outOfOfficeLogic', () => {
    let logic: ReturnType<typeof outOfOfficeLogic.build>
    let away: Record<string, unknown>[]
    let listCalls: number

    function mountWithFlag(enabled: boolean): void {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_OUT_OF_OFFICE]: enabled })
        logic = outOfOfficeLogic()
        logic.mount()
    }

    beforeEach(() => {
        away = [entry(MOCK_SECOND_BASIC_USER)]
        listCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/out_of_office/': () => {
                    listCalls += 1
                    return [200, { count: away.length, next: null, previous: null, results: away }]
                },
            },
            post: {
                '/api/projects/:team_id/conversations/out_of_office/me/': () => {
                    away = [...away, entry(MOCK_DEFAULT_BASIC_USER)]
                    return [201, entry(MOCK_DEFAULT_BASIC_USER)]
                },
            },
            delete: {
                '/api/projects/:team_id/conversations/out_of_office/me/': () => {
                    away = away.filter((row) => row.id !== `ooo-${MOCK_DEFAULT_BASIC_USER.id}`)
                    return [204]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it('marks teammates who are away, and not you while you work', async () => {
        mountWithFlag(true)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ myEntry: null })
        expect([...logic.values.awayUserIds]).toEqual([MOCK_SECOND_BASIC_USER.id])
    })

    it('sets you away and back, reloading the list each time', async () => {
        mountWithFlag(true)
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.setAway(true))
            .toFinishAllListeners()
            .toMatchValues({ myEntry: expect.objectContaining({ id: `ooo-${MOCK_DEFAULT_BASIC_USER.id}` }) })

        await expectLogic(logic, () => logic.actions.setAway(false))
            .toFinishAllListeners()
            .toMatchValues({ myEntry: null })
    })

    it('asks nothing while the flag is off', async () => {
        mountWithFlag(false)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ entries: [], enabled: false })
        expect(listCalls).toBe(0)
    })
})
