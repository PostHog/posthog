import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FALLBACK_DATA_COLOR_THEME } from 'lib/colors'
import { dataThemeLogic } from 'lib/logic/dataThemeLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

describe('dataThemeLogic', () => {
    let logic: ReturnType<typeof dataThemeLogic.build>

    afterEach(() => {
        logic?.unmount()
        delete window.POSTHOG_RENDER_QUERY_PAYLOAD
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it('getTheme falls back to the built-in default when the list resolved but no theme matched', async () => {
        window.POSTHOG_RENDER_QUERY_PAYLOAD = { themes: [] } as any
        initKeaTests()
        logic = dataThemeLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ defaultTheme: null })
        expect(logic.values.getTheme(undefined)).toEqual(FALLBACK_DATA_COLOR_THEME)
        expect(logic.values.getTheme(999)).toEqual(FALLBACK_DATA_COLOR_THEME)
    })

    it('getTheme returns null while the themes list is still loading', async () => {
        window.POSTHOG_RENDER_QUERY_PAYLOAD = { themes: [] } as any
        initKeaTests()
        logic = dataThemeLogic()
        logic.mount()
        logic.actions.setThemes(null)

        await expectLogic(logic).toMatchValues({ themes: null })
        expect(logic.values.getTheme(undefined)).toBeNull()
    })

    it('getTheme falls back to the built-in default when loading themes fails', async () => {
        silenceKeaLoadersErrors()
        jest.spyOn(api.dataColorThemes, 'list').mockRejectedValue(new Error('Unable to load themes'))
        initKeaTests()
        logic = dataThemeLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadThemesFailure']).toMatchValues({ themes: [] })
        expect(logic.values.getTheme(undefined)).toEqual(FALLBACK_DATA_COLOR_THEME)
    })
})
