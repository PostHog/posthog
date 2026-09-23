import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { osFrameName } from '../bridge/osFrame'
import { osStoreOpenApp } from '../store/osStoreMessages'
import { osWindowsLogic } from '../windows/osWindowsLogic'
import { osDockLogic } from './osDockLogic'

describe('osDockLogic', () => {
    let logic: ReturnType<typeof osDockLogic.build>

    const windowAt = (path: string): string => {
        const found = osWindowsLogic.values.windows.find((w) => w.path === path)
        if (!found) {
            throw new Error(`no window at ${path}`)
        }
        return found.id
    }
    const state = (id: string): { minimized: boolean; focused: boolean } => ({
        minimized: osWindowsLogic.values.windows.find((w) => w.id === id)?.minimized ?? false,
        focused: osWindowsLogic.values.focusedWindow?.id === id,
    })

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({ get: { '/api/environments/:team_id/user_product_list/': { results: [] } } })
        initKeaTests()
        router.actions.push(`/project/${MOCK_TEAM_ID}${urls.os()}`)
        logic = osDockLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        document.body.innerHTML = ''
    })

    it('minimizes the focused window, restores it, and focuses a window in the background', () => {
        osWindowsLogic.actions.openWindow(urls.surveys())
        osWindowsLogic.actions.openWindow(urls.featureFlags())
        const surveys = windowAt(urls.surveys())
        const flags = windowAt(urls.featureFlags())

        logic.actions.activateWindow(flags)
        expect(state(flags)).toEqual({ minimized: true, focused: false })
        expect(state(surveys)).toEqual({ minimized: false, focused: true })

        logic.actions.activateWindow(flags)
        expect(state(flags)).toEqual({ minimized: false, focused: true })

        logic.actions.activateWindow(surveys)
        expect(state(surveys)).toEqual({ minimized: false, focused: true })
        expect(state(flags)).toEqual({ minimized: false, focused: false })
        expect(logic.values.dock.windows.map((item) => [item.windowId, item.focused])).toEqual([
            [surveys, true],
            [flags, false],
        ])
    })

    it('opens the App Store once, then treats it like its window', () => {
        logic.actions.openAppStore()
        logic.actions.openAppStore()

        const store = windowAt(urls.osAppStore())
        expect(osWindowsLogic.values.windows).toHaveLength(1)
        expect(logic.values.dock.store).toEqual({ windowId: store, focused: false, minimized: true })

        logic.actions.openAppStore()
        expect(logic.values.dock.store).toEqual({ windowId: store, focused: true, minimized: false })
    })

    it('opens the app an App Store window asks for, and ignores keys it does not know', async () => {
        const frame = document.createElement('iframe')
        document.body.appendChild(frame)
        const frameWindow = frame.contentWindow as Window
        frameWindow.name = osFrameName('store1')
        const post = (key: string): void => {
            window.dispatchEvent(
                new MessageEvent('message', {
                    data: osStoreOpenApp(key),
                    origin: window.location.origin,
                    source: frameWindow,
                })
            )
        }

        await expectLogic(logic, () => {
            post('https://evil.example.com')
            post('Surveys')
        }).toDispatchActions(['openStoreApp', 'openStoreApp'])

        expect(osWindowsLogic.values.windows.map((w) => w.path)).toEqual([urls.surveys()])
    })
})
