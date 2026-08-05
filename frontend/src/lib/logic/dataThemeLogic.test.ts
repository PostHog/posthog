import { expectLogic } from 'kea-test-utils'

import api, { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { DataColorThemeModel } from '~/types'

import { dataThemeLogic } from './dataThemeLogic'

const theme = { id: 1, name: 'Default', colors: [] } as unknown as DataColorThemeModel

describe('dataThemeLogic', () => {
    let logic: ReturnType<typeof dataThemeLogic.build>

    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('does not load themes on mount before the current team ID is known', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(false)
        const listThemes = jest.spyOn(api.dataColorThemes, 'list').mockResolvedValue([theme])

        logic = dataThemeLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadThemesSuccess']).toMatchValues({ themes: null })
        expect(listThemes).not.toHaveBeenCalled()
    })

    it('loads themes once the current team ID is known', async () => {
        jest.spyOn(ApiConfig, 'hasCurrentTeamId').mockReturnValue(true)
        const listThemes = jest.spyOn(api.dataColorThemes, 'list').mockResolvedValue([theme])

        logic = dataThemeLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadThemesSuccess'])
            .toMatchValues({ themes: [theme] })
        expect(listThemes).toHaveBeenCalled()
    })
})
