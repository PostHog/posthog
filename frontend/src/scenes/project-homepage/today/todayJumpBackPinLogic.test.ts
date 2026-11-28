import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todayJumpBackPinLogic } from './todayJumpBackPinLogic'

describe('todayJumpBackPinLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        [500, true, []],
        [200, false, ['dash']],
    ])('marks the search as failed only when the request fails (status %s)', async (status, failed, ids) => {
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/search/': () => [
                    status,
                    status === 200
                        ? {
                              results: [
                                  {
                                      entry: { id: 'dash', path: 'Dashboards/Growth', type: 'dashboard', ref: '1' },
                                      rank: [],
                                  },
                              ],
                          }
                        : { detail: 'error' },
                ],
            },
        })
        const logic = todayJumpBackPinLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadPinSearchResults('growth'))
            .toDispatchActions([status === 200 ? 'loadPinSearchResultsSuccess' : 'loadPinSearchResultsFailure'])
            .toMatchValues({ pinSearchFailed: failed })
        expect(logic.values.pinSearchResults.map((entry) => entry.id)).toEqual(ids)
    })
})
