import { expectLogic } from 'kea-test-utils'

import { brandDataColorPalette } from '@posthog/quill-tokens'

import api from 'lib/api'
import { FALLBACK_DATA_COLOR_THEME } from 'lib/colors'
import { FEATURE_FLAGS } from 'lib/constants'
import { dataThemeLogic } from 'lib/logic/dataThemeLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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

    it.each([
        [false, 1, '#111111'],
        [true, 1, brandDataColorPalette[0]],
        [true, 2, '#222222'],
    ])('with brand flag %s, theme %s resolves preset-1 to %s', async (flagOn, themeId, expected) => {
        window.POSTHOG_RENDER_QUERY_PAYLOAD = {
            themes: [
                { id: 1, name: 'Default Theme', colors: ['#111111'], is_global: true },
                { id: 2, name: 'Custom', colors: ['#222222'], is_global: false },
            ],
        } as any
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.BRAND_DATA_COLORS]: flagOn })
        logic = dataThemeLogic()
        logic.mount()

        expect(logic.values.getTheme(themeId)?.['preset-1']).toEqual(expected)
    })
})
