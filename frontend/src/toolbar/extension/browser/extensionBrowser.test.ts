import { APP_MESSAGE_OPEN_URL, APP_MESSAGE_PING } from '../messaging/appMessages'

const createTab = jest.fn(async () => ({ id: 2 }))
const openSidePanel = jest.fn(async () => undefined)
const setStorage = jest.fn(async () => undefined)

// `extensionBrowser.ts` reads `browser` when the module loads, so the fake goes in before the import.
;(globalThis as unknown as { browser: unknown }).browser = {
    tabs: { create: createTab },
    sidePanel: { open: openSidePanel },
    storage: { local: { set: setStorage } },
}

describe('respondToAppMessage', () => {
    let respondToAppMessage: typeof import('./extensionBrowser').respondToAppMessage

    beforeAll(async () => {
        ;({ respondToAppMessage } = await import('./extensionBrowser'))
    })

    beforeEach(() => {
        createTab.mockClear()
        setStorage.mockClear()
        openSidePanel.mockReset()
    })

    test('answers a ping', async () => {
        await expect(respondToAppMessage({ type: APP_MESSAGE_PING }, {})).resolves.toEqual({ installed: true })
    })

    test.each([
        ['an unknown message', { type: 'posthog-toolbar-extension:later-feature' }],
        ['a javascript URL', { type: APP_MESSAGE_OPEN_URL, url: 'javascript:alert(1)' }],
        ['a data URL', { type: APP_MESSAGE_OPEN_URL, url: 'data:text/html,hi' }],
        ['a missing URL', { type: APP_MESSAGE_OPEN_URL }],
    ])('ignores %s', (_, message) => {
        expect(respondToAppMessage(message, {})).toBeUndefined()

        expect(createTab).not.toHaveBeenCalled()
    })

    test.each([
        ['opens', async () => undefined, true],
        ['refuses to open', async () => Promise.reject(new Error('user gesture required')), false],
    ])('opens the URL in a new tab when Chrome %s the side panel', async (_, open, panelOpened) => {
        openSidePanel.mockImplementation(open)

        const response = await respondToAppMessage(
            { type: APP_MESSAGE_OPEN_URL, url: 'https://example.com/' },
            { origin: 'https://eu.posthog.com', tab: { windowId: 7 } }
        )

        expect(response).toEqual({ opened: true, panelOpened })
        expect(createTab).toHaveBeenCalledWith({ url: 'https://example.com/' })
        expect(openSidePanel).toHaveBeenCalledWith({ windowId: 7 })
        expect(setStorage).toHaveBeenCalledWith({ posthogUiHost: 'https://eu.posthog.com' })
    })

    test('answers that the tab opened when Chrome takes too long to open the side panel', async () => {
        jest.useFakeTimers()
        try {
            openSidePanel.mockImplementation(() => new Promise(() => undefined))

            const response = respondToAppMessage(
                { type: APP_MESSAGE_OPEN_URL, url: 'https://example.com/' },
                { tab: { windowId: 7 } }
            )
            await jest.advanceTimersByTimeAsync(1000)

            await expect(response).resolves.toEqual({ opened: true, panelOpened: false })
        } finally {
            jest.useRealTimers()
        }
    })
})
