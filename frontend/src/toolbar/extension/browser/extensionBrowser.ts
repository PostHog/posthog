import { PAGE_TOOLBAR_PORT, PageToolbarTokens } from '../messaging/pageToolbarBridge'

// Firefox and Chrome both expose the promise-based `chrome.*` namespace to Manifest V3 extensions.
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
        getURL: (path: string) => string
    }
    permissions: {
        contains: (permissions: ExtensionPermissions) => Promise<boolean>
        request: (permissions: ExtensionPermissions) => Promise<boolean>
        // Firefox adds `data_collection`, and Chrome leaves it out.
        getAll: () => Promise<ExtensionPermissions & { data_collection?: string[] }>
        onAdded: ExtensionEvent<() => void>
        onRemoved: ExtensionEvent<() => void>
    }
    action: {
        onClicked: ExtensionEvent<() => void>
    }
    sidePanel?: {
        setPanelBehavior: (behavior: { openPanelOnActionClick: boolean }) => Promise<void>
    }
    sidebarAction?: {
        toggle: () => Promise<void>
    }
}

// Firefox puts its own APIs, such as `sidebarAction`, only on `browser`.
const extensionBrowser = ((globalThis as unknown as { browser?: ExtensionBrowserApi }).browser ??
    (globalThis as unknown as { chrome: ExtensionBrowserApi }).chrome) as ExtensionBrowserApi

// pinned: extension storage key, renaming it resets the saved PostHog host
const UI_HOST_STORAGE_KEY = 'posthogUiHost'

const CONTENT_SCRIPT_FILE = 'content.js'

export function openPanelFromToolbarButton(): void {
    if (extensionBrowser.sidePanel) {
        void extensionBrowser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
        return
    }
    const sidebarAction = extensionBrowser.sidebarAction
    if (sidebarAction) {
        // Firefox opens a sidebar only from a user action, so the toggle must run in the click listener without an await.
        extensionBrowser.action.onClicked.addListener(() => void sidebarAction.toggle())
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
    // Match patterns cover every port of a host, and Firefox rejects a pattern that names one.
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

/**
 * Firefox asks the user at install whether the extension may send usage data, from the manifest's
 * `data_collection_permissions`. Chrome has no such choice, so usage data is allowed there.
 */
export async function canSendUsageData(): Promise<boolean> {
    const { data_collection } = await extensionBrowser.permissions.getAll()
    // pinned: Firefox data collection category, the manifest declares the same key
    return !data_collection || data_collection.includes('technicalAndInteraction')
}

/** Firefox fires these when the user changes the data collection choice in the add-on's settings. */
export function onPermissionsChange(handler: () => void): () => void {
    extensionBrowser.permissions.onAdded.addListener(handler)
    extensionBrowser.permissions.onRemoved.addListener(handler)
    return () => {
        extensionBrowser.permissions.onAdded.removeListener(handler)
        extensionBrowser.permissions.onRemoved.removeListener(handler)
    }
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
