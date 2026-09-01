import { expectLogic } from 'kea-test-utils'

import { DEFAULT_DATA_COLOR_THEME } from 'lib/colors'
import { dataThemeLogic } from 'lib/logic/dataThemeLogic'

import { initKeaTests } from '~/test/init'

describe('dataThemeLogic', () => {
    let logic: ReturnType<typeof dataThemeLogic.build>

    afterEach(() => {
        logic?.unmount()
        delete window.POSTHOG_RENDER_QUERY_PAYLOAD
    })

    it('getTheme falls back to the built-in default when no theme resolves', async () => {
        // A blank chart shipped once because getTheme returned null when the themes list resolved
        // empty. Lock in the fallback so charts keep drawing with the built-in colors.
        window.POSTHOG_RENDER_QUERY_PAYLOAD = { themes: [] } as any
        initKeaTests()
        logic = dataThemeLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ defaultTheme: null })
        expect(logic.values.getTheme(undefined)).toEqual(DEFAULT_DATA_COLOR_THEME)
        expect(logic.values.getTheme(999)).toEqual(DEFAULT_DATA_COLOR_THEME)
    })
})
