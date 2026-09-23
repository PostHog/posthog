import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { osFrameName } from '../bridge/osFrame'
import { osMenuBarLogic } from '../shell/osMenuBarLogic'
import { osStoreOpenApp } from '../store/osStoreMessages'
import { osWindowsLogic } from '../windows/osWindowsLogic'
import { OS_DOCK_STORE_KEY } from './osDockItems'
import { osDockLogic } from './osDockLogic'

const PINS_KEY = `posthog-os-dock:${MOCK_TEAM_ID}`

describe('osDockLogic', () => {
    let logic: ReturnType<typeof osDockLogic.build>
    let menuBar: ReturnType<typeof osMenuBarLogic.build>

    const windowsAt = (path: string): string[] =>
        osWindowsLogic.values.windows.filter((w) => w.path === path).map((w) => w.id)
    const windowAt = (path: string): string => {
        const [found] = windowsAt(path)
        if (!found) {
            throw new Error(`no window at ${path}`)
        }
        return found
    }
    const state = (id: string): { minimized: boolean; focused: boolean } => ({
        minimized: osWindowsLogic.values.windows.find((w) => w.id === id)?.minimized ?? false,
        focused: osWindowsLogic.values.focusedWindow?.id === id,
    })
    const dockKeys = (): string[] => logic.values.dock.apps.map((item) => item.key)
    const remount = (): void => {
        menuBar.unmount()
        logic.unmount()
        logic = osDockLogic()
        logic.mount()
        menuBar = osMenuBarLogic()
        menuBar.mount()
    }

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({ get: { '/api/environments/:team_id/user_product_list/': { results: [] } } })
        initKeaTests()
        router.actions.push(`/project/${MOCK_TEAM_ID}${urls.os()}`)
        logic = osDockLogic()
        logic.mount()
        menuBar = osMenuBarLogic()
        menuBar.mount()
    })

    afterEach(() => {
        menuBar?.unmount()
        logic?.unmount()
        document.body.innerHTML = ''
    })

    it('minimizes the focused app, restores it, and focuses an app in the background', () => {
        osWindowsLogic.actions.openWindow(urls.surveys())
        osWindowsLogic.actions.openWindow(urls.featureFlags())
        const surveys = windowAt(urls.surveys())
        const flags = windowAt(urls.featureFlags())

        logic.actions.activateItem('Feature flags')
        expect(state(flags)).toEqual({ minimized: true, focused: false })
        expect(state(surveys)).toEqual({ minimized: false, focused: true })

        logic.actions.activateItem('Feature flags')
        expect(state(flags)).toEqual({ minimized: false, focused: true })

        logic.actions.activateItem('Surveys')
        expect(state(surveys)).toEqual({ minimized: false, focused: true })
        expect(logic.values.dock.apps.map((item) => [item.key, item.focused])).toEqual([
            ['Surveys', true],
            ['Feature flags', false],
        ])
    })

    it('keeps a pinned app after its last window closes and after a reload, and drops it once unpinned', () => {
        osWindowsLogic.actions.openWindow(urls.surveys())
        osWindowsLogic.actions.openWindow(urls.featureFlags())
        logic.actions.pinApp('Surveys')

        logic.actions.closeItem('Surveys')
        logic.actions.closeItem('Feature flags')
        expect(dockKeys()).toEqual(['Surveys'])

        remount()
        expect(dockKeys()).toEqual(['Surveys'])

        logic.actions.activateItem('Surveys')
        expect(windowsAt(urls.surveys())).toHaveLength(1)

        logic.actions.unpinApp('Surveys')
        logic.actions.closeItem('Surveys')
        remount()
        expect(dockKeys()).toEqual([])
    })

    it('pins only apps it knows, once each, and never the App Store or a window no app claims', () => {
        osWindowsLogic.actions.openWindow(urls.persons())
        const person = logic.values.dock.apps[0].key

        logic.actions.pinApp('Surveys')
        logic.actions.pinApp('Surveys')
        logic.actions.pinApp('Not an app')
        logic.actions.pinApp(OS_DOCK_STORE_KEY)
        logic.actions.pinApp(person)

        expect(logic.values.pinnedAppKeys).toEqual(['Surveys'])
        expect(JSON.parse(localStorage.getItem(PINS_KEY) ?? 'null')).toEqual({ version: 1, keys: ['Surveys'] })
    })

    it('keeps earlier pins when localStorage refuses the write', () => {
        const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('QuotaExceededError')
        })
        try {
            logic.actions.pinApp('Surveys')
            logic.actions.pinApp('Feature flags')
            expect(dockKeys()).toEqual(['Surveys', 'Feature flags'])
        } finally {
            setItem.mockRestore()
        }
    })

    it('follows pins changed or cleared in another tab', () => {
        localStorage.setItem(PINS_KEY, JSON.stringify({ version: 1, keys: ['Surveys'] }))
        window.dispatchEvent(new StorageEvent('storage', { key: PINS_KEY }))
        expect(dockKeys()).toEqual(['Surveys'])

        localStorage.clear()
        window.dispatchEvent(new StorageEvent('storage', { key: null }))
        expect(dockKeys()).toEqual([])
    })

    it('keeps a window on its app when it navigates to a page several apps could claim', () => {
        const aiObservability = logic.values.knownApps.find((app) => app.href === urls.aiObservabilityDashboard())
        if (!aiObservability) {
            throw new Error('no AI observability app in the catalog')
        }
        osWindowsLogic.actions.openWindow(urls.aiObservabilityDashboard())
        const id = windowAt(urls.aiObservabilityDashboard())

        osWindowsLogic.actions.windowNavigated(id, '/ai-observability/traces')

        expect(dockKeys()).toEqual([aiObservability.key])
        expect(menuBar.values.appMenu?.app.key).toEqual(aiObservability.key)
    })

    it('gives a page an app menu lists to that app, the same as the menu bar', () => {
        osWindowsLogic.actions.openWindow(urls.alerts())

        expect(dockKeys()).toEqual(['Product analytics'])
        expect(menuBar.values.appMenu?.app.key).toEqual('Product analytics')
    })

    it.each([
        ['text that is not JSON', '{nope', []],
        ['another version', JSON.stringify({ version: 99, keys: ['Surveys'] }), []],
        ['keys that are not a list', JSON.stringify({ version: 1, keys: 'Surveys' }), []],
        [
            'entries that are not strings, or repeat',
            JSON.stringify({ version: 1, keys: [1, null, { key: 'Surveys' }, 'Surveys', 'Surveys', ''] }),
            ['Surveys'],
        ],
    ])('reads stored pins with %s without breaking the dock', (_, stored, expected) => {
        localStorage.setItem(PINS_KEY, stored)

        remount()

        expect(logic.values.pinnedAppKeys).toEqual(expected)
        expect(dockKeys()).toEqual(expected)
    })

    it('minimizes, restores and closes every window of an app, and opens another window', () => {
        osWindowsLogic.actions.openWindow(urls.surveys())
        osWindowsLogic.actions.openWindow(urls.surveys(), { newWindow: true })
        osWindowsLogic.actions.openWindow(urls.featureFlags())
        const surveys = windowsAt(urls.surveys())

        logic.actions.minimizeItem('Surveys')
        expect(surveys.map((id) => state(id).minimized)).toEqual([true, true])

        logic.actions.restoreItem('Surveys')
        expect(surveys.map((id) => state(id).minimized)).toEqual([false, false])
        expect(osWindowsLogic.values.focusedWindow?.path).toEqual(urls.surveys())

        logic.actions.openItemInNewWindow('Surveys')
        expect(windowsAt(urls.surveys())).toHaveLength(3)

        logic.actions.closeItem('Surveys')
        expect(osWindowsLogic.values.windows.map((w) => w.path)).toEqual([urls.featureFlags()])
    })

    it('opens the App Store once, then treats it like its window', () => {
        logic.actions.openAppStore()
        logic.actions.openAppStore()

        const store = windowAt(urls.osAppStore())
        expect(osWindowsLogic.values.windows).toHaveLength(1)
        expect(state(store)).toEqual({ minimized: true, focused: false })

        logic.actions.openAppStore()
        expect(state(store)).toEqual({ minimized: false, focused: true })
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
