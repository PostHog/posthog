// Firefox and Chrome both expose the promise-based `chrome.*` namespace to Manifest V3 extensions.
// Only the calls the side panel and the background script make are typed here.
interface ExtensionTab {
    id?: number
    url?: string
}

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

interface ExtensionEvent<Listener> {
    addListener: (listener: Listener) => void
    removeListener: (listener: Listener) => void
}

interface ExtensionBrowserApi {
    tabs: {
        query: (query: { active: true; windowId?: number; currentWindow?: true }) => Promise<ExtensionTab[]>
        create: (properties: { url: string }) => Promise<unknown>
        onActivated: ExtensionEvent<(activeInfo: TabActiveInfo) => void>
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
    permissions: {
        contains: (permissions: ExtensionPermissions) => Promise<boolean>
        request: (permissions: ExtensionPermissions) => Promise<boolean>
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
export async function requestHostPermission(uiHost: string): Promise<boolean> {
    return await extensionBrowser.permissions.request(originPattern(uiHost))
}
