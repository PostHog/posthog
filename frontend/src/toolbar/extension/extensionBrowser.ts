import {
    CONTENT_MESSAGE_SOURCE,
    ContentCommand,
    ContentMessage,
    ContentStatus,
    IDLE_CONTENT_STATUS,
    SELECTED_ELEMENT_STORAGE_KEY,
    SelectedElement,
    isSelectedElement,
} from './contentBridge'
import { PageFlagOverrides, applyPageFlagOverrides } from './pageFlagOverrides'

// Firefox and Chrome both expose the promise-based `chrome.*` namespace to Manifest V3 extensions.
// Only the calls the popup and the content script make are typed here.
interface ExtensionTab {
    id?: number
    url?: string
}

interface StorageChange {
    newValue?: unknown
}

type StorageChangeListener = (changes: Record<string, StorageChange>, areaName: string) => void

type RuntimeMessageListener = (message: unknown, sender: unknown, sendResponse: (response: unknown) => void) => void

interface ExtensionPermissions {
    origins: string[]
}

interface ExtensionBrowserApi {
    tabs: {
        query: (query: { active: true; currentWindow: true }) => Promise<ExtensionTab[]>
        create: (properties: { url: string }) => Promise<unknown>
        sendMessage: (tabId: number, message: ContentMessage) => Promise<unknown>
    }
    storage: {
        local: {
            get: (key: string) => Promise<Record<string, unknown>>
            set: (items: Record<string, unknown>) => Promise<void>
            remove: (key: string) => Promise<void>
        }
        onChanged: {
            addListener: (listener: StorageChangeListener) => void
            removeListener: (listener: StorageChangeListener) => void
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
    }
    permissions: {
        contains: (permissions: ExtensionPermissions) => Promise<boolean>
        request: (permissions: ExtensionPermissions) => Promise<boolean>
    }
}

const extensionBrowser = (globalThis as unknown as { chrome: ExtensionBrowserApi }).chrome

// pinned: extension storage key, renaming it resets the saved PostHog host
const UI_HOST_STORAGE_KEY = 'posthogUiHost'

const CONTENT_SCRIPT_FILE = 'content.js'

export async function getActiveTab(): Promise<ExtensionTab | null> {
    // The `activeTab` permission exposes the URL, and lets the popup run scripts in the tab, only after the
    // user opens the popup.
    const [tab] = await extensionBrowser.tabs.query({ active: true, currentWindow: true })
    return tab ?? null
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

function contentMessage(command: ContentCommand): ContentMessage {
    return { source: CONTENT_MESSAGE_SOURCE, command }
}

/** Returns the idle status when the content script isn't in the tab yet, without injecting it. */
export async function getContentStatus(tabId: number): Promise<ContentStatus> {
    try {
        return ((await extensionBrowser.tabs.sendMessage(tabId, contentMessage({ type: 'get-status' }))) ??
            IDLE_CONTENT_STATUS) as ContentStatus
    } catch {
        return IDLE_CONTENT_STATUS
    }
}

/** Injects the content script on first use. The script ignores a second injection into the same page. */
export async function sendContentCommand(tabId: number, command: ContentCommand): Promise<ContentStatus> {
    try {
        return (await extensionBrowser.tabs.sendMessage(tabId, contentMessage(command))) as ContentStatus
    } catch {
        // No receiver means the content script isn't in the tab yet.
        await extensionBrowser.scripting.executeScript({ target: { tabId }, files: [CONTENT_SCRIPT_FILE] })
        return (await extensionBrowser.tabs.sendMessage(tabId, contentMessage(command))) as ContentStatus
    }
}

export function onContentCommand(handler: (message: unknown) => ContentStatus | null): void {
    extensionBrowser.runtime.onMessage.addListener((message, _sender, sendResponse) => {
        const status = handler(message)
        if (status) {
            sendResponse(status)
        }
    })
}

/** Pass null to read the page's flag overrides without a change. */
export async function runPageFlagOverrides(
    tabId: number,
    flags: Record<string, string | boolean> | null
): Promise<PageFlagOverrides> {
    const [injection] = await extensionBrowser.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: applyPageFlagOverrides,
        args: [flags],
    })
    return injection?.result ?? { available: false, overrides: {} }
}

export async function getStoredSelectedElement(): Promise<SelectedElement | null> {
    const stored = await extensionBrowser.storage.local.get(SELECTED_ELEMENT_STORAGE_KEY)
    const value = stored[SELECTED_ELEMENT_STORAGE_KEY]
    return isSelectedElement(value) ? value : null
}

export async function setStoredSelectedElement(selectedElement: SelectedElement): Promise<void> {
    await extensionBrowser.storage.local.set({ [SELECTED_ELEMENT_STORAGE_KEY]: selectedElement })
}

export async function clearStoredSelectedElement(): Promise<void> {
    await extensionBrowser.storage.local.remove(SELECTED_ELEMENT_STORAGE_KEY)
}

/** Returns a function that removes the listener. */
export function onStoredSelectedElementChange(handler: (selectedElement: SelectedElement | null) => void): () => void {
    const listener: StorageChangeListener = (changes, areaName) => {
        const change = changes[SELECTED_ELEMENT_STORAGE_KEY]
        if (areaName === 'local' && change) {
            handler(isSelectedElement(change.newValue) ? change.newValue : null)
        }
    }
    extensionBrowser.storage.onChanged.addListener(listener)
    return () => extensionBrowser.storage.onChanged.removeListener(listener)
}
