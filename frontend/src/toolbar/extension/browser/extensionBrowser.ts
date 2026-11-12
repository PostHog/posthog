import { APP_MESSAGE_OPEN_URL, APP_MESSAGE_PING, OpenUrlResponse, PingResponse } from '../messaging/appMessages'
import { PAGE_TOOLBAR_PORT, PageToolbarTokens } from '../messaging/pageToolbarBridge'

// Chrome exposes the promise-based `chrome.*` namespace to Manifest V3 extensions.
// Only the calls the side panel, the background script and the content script make are typed here.
interface ExtensionTab {
    id?: number
    url?: string
}

// Returning true keeps sendResponse open for an async response.
type RuntimeMessageListener = (
    message: unknown,
    sender: unknown,
    sendResponse: (response: unknown) => void
) => boolean | void

interface ExternalMessageSender {
    origin?: string
    tab?: { windowId?: number }
}

type ExternalMessageListener = (
    message: unknown,
    sender: ExternalMessageSender,
    sendResponse: (response: unknown) => void
) => boolean | void

interface ExtensionPermissions {
    origins: string[]
}

interface TabActiveInfo {
    tabId: number
    windowId: number
}

interface TabChangeInfo {
    url?: string
    status?: string
}

export interface ExtensionPort {
    name: string
    postMessage: (message: unknown) => void
    disconnect: () => void
    onMessage: ExtensionEvent<(message: unknown) => void>
    onDisconnect: ExtensionEvent<() => void>
}

interface ExtensionEvent<Listener> {
    addListener: (listener: Listener) => void
    removeListener: (listener: Listener) => void
}

interface ExtensionBrowserApi {
    tabs: {
        query: (query: { active: true; windowId?: number; currentWindow?: true }) => Promise<ExtensionTab[]>
        create: (properties: { url: string; active?: boolean }) => Promise<ExtensionTab>
        remove: (tabId: number) => Promise<void>
        connect: (tabId: number, connectInfo: { name: string }) => ExtensionPort
        sendMessage: (tabId: number, message: unknown) => Promise<unknown>
        onActivated: ExtensionEvent<(activeInfo: TabActiveInfo) => void>
        onRemoved: ExtensionEvent<(tabId: number) => void>
        onUpdated: ExtensionEvent<
            (
                tabId: number,
                changeInfo: TabChangeInfo,
                tab: ExtensionTab & { active?: boolean; windowId?: number }
            ) => void
        >
    }
    windows: {
        getCurrent: () => Promise<{ id?: number }>
    }
    storage: {
        local: {
            get: (key: string) => Promise<Record<string, unknown>>
            set: (items: Record<string, unknown>) => Promise<void>
        }
    }
    scripting: {
        executeScript: <Args extends unknown[], Result>(injection: {
            target: { tabId: number }
            files?: string[]
            world?: 'ISOLATED' | 'MAIN'
            func?: (...args: Args) => Result
            args?: Args
        }) => Promise<{ result?: Result }[]>
    }
    runtime: {
        onMessage: {
            addListener: (listener: RuntimeMessageListener) => void
        }
        onConnect: ExtensionEvent<(port: ExtensionPort) => void>
        onMessageExternal: ExtensionEvent<ExternalMessageListener>
        getURL: (path: string) => string
    }
    permissions: {
        contains: (permissions: ExtensionPermissions) => Promise<boolean>
        request: (permissions: ExtensionPermissions) => Promise<boolean>
    }
    action: {
        onClicked: ExtensionEvent<() => void>
    }
    sidePanel: {
        setPanelBehavior: (behavior: { openPanelOnActionClick: boolean }) => Promise<void>
        open: (options: { windowId: number }) => Promise<void>
    }
}

// Stories and the store listing images install a fake extension API as `browser`, because every Chrome page already
// has a `chrome` object of its own.
const extensionBrowser = ((globalThis as unknown as { browser?: ExtensionBrowserApi }).browser ??
    (globalThis as unknown as { chrome: ExtensionBrowserApi }).chrome) as ExtensionBrowserApi

// pinned: extension storage key, renaming it resets the saved PostHog host
const UI_HOST_STORAGE_KEY = 'posthogUiHost'

const CONTENT_SCRIPT_FILE = 'content.js'

export function openPanelFromToolbarButton(): void {
    void extensionBrowser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
}

/** Answers the PostHog app, which the manifest lets message the extension through `externally_connectable`. */
export function listenForAppMessages(): void {
    extensionBrowser.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
        const response = respondToAppMessage(message, sender)
        if (!response) {
            return false
        }
        void response.then(sendResponse)
        return true
    })
}

/** `undefined` for a message this version doesn't know, so it ignores what a newer app build sends. */
export function respondToAppMessage(
    message: unknown,
    sender: ExternalMessageSender
): Promise<PingResponse | OpenUrlResponse> | undefined {
    if (typeof message !== 'object' || message === null) {
        return undefined
    }
    const { type, url } = message as { type?: unknown; url?: unknown }
    if (type === APP_MESSAGE_PING) {
        return Promise.resolve({ installed: true })
    }
    if (type === APP_MESSAGE_OPEN_URL && typeof url === 'string' && isWebUrl(url)) {
        // The panel signs in to the host the user opened it from, for example EU Cloud on a fresh install.
        if (sender.origin) {
            void setStoredUiHost(sender.origin)
        }
        const windowId = sender.tab?.windowId
        // Called before any await, so Chrome can still count the click in the app as the user action it requires.
        const panelOpened =
            windowId === undefined
                ? Promise.resolve(false)
                : withTimeout(
                      extensionBrowser.sidePanel.open({ windowId }).then(
                          () => true,
                          () => false
                      ),
                      PANEL_OPEN_TIMEOUT_MS,
                      false
                  )
        return extensionBrowser.tabs.create({ url }).then(
            async () => ({ opened: true, panelOpened: await panelOpened }),
            async () => ({ opened: false, panelOpened: await panelOpened })
        )
    }
    return undefined
}

// The app gives up after a few seconds, so a slow panel must not hold back the answer that the tab opened.
const PANEL_OPEN_TIMEOUT_MS = 1000

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
    return Promise.race([promise, new Promise<T>((resolve) => setTimeout(() => resolve(fallback), timeoutMs))])
}

function isWebUrl(url: string): boolean {
    try {
        const { protocol } = new URL(url)
        return protocol === 'https:' || protocol === 'http:'
    } catch {
        return false
    }
}

export async function getActiveTab(): Promise<ExtensionTab | null> {
    const [tab] = await extensionBrowser.tabs.query({ active: true, currentWindow: true })
    return tab ?? null
}

/** Returns a function that removes the listeners. */
export function onActiveTabChange(handler: (tab: ExtensionTab | null) => void): () => void {
    let panelWindowId: number | undefined
    void extensionBrowser.windows.getCurrent().then((panelWindow) => {
        panelWindowId = panelWindow.id
    })
    const onActivated = ({ windowId }: TabActiveInfo): void => {
        if (windowId === panelWindowId) {
            void getActiveTab().then(handler, () => handler(null))
        }
    }
    const onUpdated = (
        _tabId: number,
        changeInfo: TabChangeInfo,
        tab: ExtensionTab & { active?: boolean; windowId?: number }
    ): void => {
        // A reload keeps the URL but removes everything the extension added to the page.
        if (tab.active && tab.windowId === panelWindowId && (changeInfo.url || changeInfo.status === 'complete')) {
            handler(tab)
        }
    }
    extensionBrowser.tabs.onActivated.addListener(onActivated)
    extensionBrowser.tabs.onUpdated.addListener(onUpdated)
    return () => {
        extensionBrowser.tabs.onActivated.removeListener(onActivated)
        extensionBrowser.tabs.onUpdated.removeListener(onUpdated)
    }
}

export async function openTab(url: string): Promise<void> {
    await extensionBrowser.tabs.create({ url })
}

export async function getStoredUiHost(): Promise<string | null> {
    const stored = await extensionBrowser.storage.local.get(UI_HOST_STORAGE_KEY)
    const value = stored[UI_HOST_STORAGE_KEY]
    return typeof value === 'string' ? value : null
}

export async function setStoredUiHost(uiHost: string): Promise<void> {
    await extensionBrowser.storage.local.set({ [UI_HOST_STORAGE_KEY]: uiHost })
}

function originPattern(uiHost: string): ExtensionPermissions {
    // A pattern without a port matches the host on every port.
    const { protocol, hostname } = new URL(uiHost)
    return { origins: [`${protocol}//${hostname}/*`] }
}

/** The manifest asks for every site, but the user can take access back for a site in the browser's settings. */
export async function hasHostPermission(uiHost: string): Promise<boolean> {
    return await extensionBrowser.permissions.contains(originPattern(uiHost))
}

/** Must run inside the click handler: browsers show the permission prompt only for a user gesture. */
export async function requestHostPermission(url: string): Promise<boolean> {
    return await extensionBrowser.permissions.request(originPattern(url))
}

// pinned: extension message, the panel and an already injected content script must agree on it
const CONTENT_SCRIPT_PING = 'posthog-toolbar-extension-ping'

export async function ensureContentScript(tabId: number): Promise<void> {
    const installed = await extensionBrowser.tabs.sendMessage(tabId, CONTENT_SCRIPT_PING).then(
        (response) => response === true,
        () => false
    )
    if (!installed) {
        await extensionBrowser.scripting.executeScript({ target: { tabId }, files: [CONTENT_SCRIPT_FILE] })
    }
}

export function answerContentScriptPing(): void {
    extensionBrowser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
        if (message === CONTENT_SCRIPT_PING) {
            sendResponse(true)
        }
    })
}

export function extensionFileUrl(path: string): string {
    return extensionBrowser.runtime.getURL(path)
}

export function connectToPageToolbar(tabId: number): ExtensionPort {
    return extensionBrowser.tabs.connect(tabId, { name: PAGE_TOOLBAR_PORT })
}

export function onPageToolbarConnect(handler: (port: ExtensionPort) => void): void {
    extensionBrowser.runtime.onConnect.addListener((port) => {
        if (port.name === PAGE_TOOLBAR_PORT) {
            handler(port)
        }
    })
}

const PAGE_AGENT_FILE = 'page-agent.js'

/** Runs the page agent in the page's own world, where it can call the page's posthog-js for the content script. */
export async function injectPageAgent(tabId: number): Promise<void> {
    await extensionBrowser.scripting.executeScript({ target: { tabId }, world: 'MAIN', files: [PAGE_AGENT_FILE] })
}

export async function waitForTabUrl(
    url: string,
    matches: (tabUrl: string) => boolean,
    { timeoutMs, active }: { timeoutMs: number; active: boolean }
): Promise<string> {
    const tab = await extensionBrowser.tabs.create({ url, active })
    const tabId = tab.id
    if (tabId === undefined) {
        throw new Error('The browser did not open the tab')
    }
    return await new Promise((resolve, reject) => {
        const finish = (result: { url: string } | { error: Error }): void => {
            clearTimeout(timeout)
            extensionBrowser.tabs.onUpdated.removeListener(onUpdated)
            extensionBrowser.tabs.onRemoved.removeListener(onRemoved)
            if ('url' in result) {
                void extensionBrowser.tabs.remove(tabId).catch(() => undefined)
                resolve(result.url)
            } else {
                reject(result.error)
            }
        }
        const onUpdated = (updatedTabId: number, changeInfo: TabChangeInfo): void => {
            if (updatedTabId === tabId && changeInfo.url && matches(changeInfo.url)) {
                finish({ url: changeInfo.url })
            }
        }
        const onRemoved = (removedTabId: number): void => {
            if (removedTabId === tabId) {
                finish({ error: new Error('The tab closed before it finished') })
            }
        }
        const timeout = setTimeout(() => {
            void extensionBrowser.tabs.remove(tabId).catch(() => undefined)
            finish({ error: new Error('The tab did not finish in time') })
        }, timeoutMs)
        extensionBrowser.tabs.onUpdated.addListener(onUpdated)
        extensionBrowser.tabs.onRemoved.addListener(onRemoved)
    })
}

// pinned: extension storage key, renaming it signs every project out of the toolbar
const TOKENS_STORAGE_KEY = 'posthogToolbarTokens'

export async function getStoredTokens(key: string): Promise<PageToolbarTokens | null> {
    const stored = await extensionBrowser.storage.local.get(TOKENS_STORAGE_KEY)
    const tokensByKey = stored[TOKENS_STORAGE_KEY] as Record<string, PageToolbarTokens> | undefined
    const tokens = tokensByKey?.[key]
    return tokens && typeof tokens.accessToken === 'string' && typeof tokens.clientId === 'string' ? tokens : null
}

export async function setStoredTokens(key: string, tokens: PageToolbarTokens | null): Promise<void> {
    const stored = await extensionBrowser.storage.local.get(TOKENS_STORAGE_KEY)
    const tokensByKey = { ...(stored[TOKENS_STORAGE_KEY] as Record<string, PageToolbarTokens> | undefined) }
    if (tokens) {
        tokensByKey[key] = tokens
    } else {
        delete tokensByKey[key]
    }
    await extensionBrowser.storage.local.set({ [TOKENS_STORAGE_KEY]: tokensByKey })
}
