// Firefox and Chrome both expose the promise-based `chrome.*` namespace to Manifest V3 extensions.
// Only the calls the popup makes are typed here.
interface ExtensionTab {
    url?: string
}

interface ExtensionPermissions {
    origins: string[]
}

interface ExtensionBrowserApi {
    tabs: {
        query: (query: { active: true; currentWindow: true }) => Promise<ExtensionTab[]>
        create: (properties: { url: string }) => Promise<unknown>
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
}

const extensionBrowser = (globalThis as unknown as { chrome: ExtensionBrowserApi }).chrome

// pinned: extension storage key, renaming it resets the saved PostHog host
const UI_HOST_STORAGE_KEY = 'posthogUiHost'

export async function getActiveTabUrl(): Promise<string | null> {
    // The `activeTab` permission exposes the URL only after the user opens the popup.
    const [tab] = await extensionBrowser.tabs.query({ active: true, currentWindow: true })
    return tab?.url ?? null
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

export async function hasHostPermission(uiHost: string): Promise<boolean> {
    return await extensionBrowser.permissions.contains(originPattern(uiHost))
}

/** Must run inside the click handler: browsers show the permission prompt only for a user gesture. */
export async function requestHostPermission(uiHost: string): Promise<boolean> {
    return await extensionBrowser.permissions.request(originPattern(uiHost))
}
