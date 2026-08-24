import { expectLogic } from 'kea-test-utils'

import { dataThemeLogic } from 'lib/logic/dataThemeLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('dataThemeLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
    })

    it('retries loading themes after a transient failure', async () => {
        let attempts = 0
        useMocks({
            get: {
                '/api/environments/:team_id/data_color_themes/': () => {
                    attempts += 1
                    // Fail the first mount load, then recover so charts get a palette.
                    if (attempts === 1) {
                        return [500, { detail: 'boom' }]
                    }
                    return [200, [{ id: 1, name: 'Default', colors: ['#111111'], is_global: true }]]
                },
            },
        })

        dataThemeLogic.mount()

        await expectLogic(dataThemeLogic)
            .delay(3500)
            .toDispatchActions(['loadThemesFailure', 'loadThemes', 'loadThemesSuccess'])
            .toMatchValues({ themes: [{ id: 1, name: 'Default', colors: ['#111111'], is_global: true }] })
        expect(attempts).toBe(2)
    })
})
