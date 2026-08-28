import { themeLogic } from 'lib/logic/themeLogic'

import { initKeaTests } from '~/test/init'

// Trigger visibilitychange after mutating document.hidden, so the kea disposables
// plugin pauses/resumes listeners exactly as it does in the browser
const setHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (hidden ? 'hidden' : 'visible'),
    })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('themeLogic', () => {
    let systemPrefersDark: boolean
    let changeListeners: Set<(e: MediaQueryListEvent) => void>

    const emitSystemThemeChange = (dark: boolean): void => {
        systemPrefersDark = dark
        changeListeners.forEach((listener) => listener({ matches: dark } as MediaQueryListEvent))
    }

    beforeEach(() => {
        systemPrefersDark = false
        changeListeners = new Set()
        window.matchMedia = jest.fn(
            (query: string) =>
                ({
                    get matches() {
                        return systemPrefersDark
                    },
                    media: query,
                    addEventListener: (_type: string, listener: (e: MediaQueryListEvent) => void): void => {
                        changeListeners.add(listener)
                    },
                    removeEventListener: (_type: string, listener: (e: MediaQueryListEvent) => void): void => {
                        changeListeners.delete(listener)
                    },
                }) as unknown as MediaQueryList
        )
        initKeaTests()
        setHidden(false)
        themeLogic.mount()
    })

    afterEach(() => {
        setHidden(false)
    })

    it('syncs darkModeSystemPreference when the system theme changes while the tab is visible', () => {
        expect(themeLogic.values.darkModeSystemPreference).toBe(false)
        emitSystemThemeChange(true)
        expect(themeLogic.values.darkModeSystemPreference).toBe(true)
    })

    it('picks up a system theme change that happened while the tab was hidden', () => {
        setHidden(true)
        emitSystemThemeChange(true) // the paused listener misses this; only the resume re-read can catch it
        setHidden(false)
        expect(themeLogic.values.darkModeSystemPreference).toBe(true)

        // The change listener must be re-attached after resume, so live changes still apply
        emitSystemThemeChange(false)
        expect(themeLogic.values.darkModeSystemPreference).toBe(false)
    })
})
