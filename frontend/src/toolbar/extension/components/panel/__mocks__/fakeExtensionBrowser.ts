import type { ExtensionPort } from '../../../browser/extensionBrowser'
import type { PageToolbarMessage, PageToolbarState } from '../../../messaging/pageToolbarBridge'

// Stories render the side panel outside an extension. `extensionBrowser.ts` reads `browser` when the module loads, so
// a story imports this module before any panel module.

interface FakeExtensionConfig {
    tabUrl: string
    pageState: PageToolbarState
    storage: Record<string, unknown>
}

let config: FakeExtensionConfig | null = null

export function configureFakeExtensionBrowser(next: FakeExtensionConfig): void {
    config = next
}

function fakeEvent(): { addListener: () => void; removeListener: () => void } {
    return { addListener: () => undefined, removeListener: () => undefined }
}

function fakePort(): ExtensionPort {
    const listeners: ((message: unknown) => void)[] = []
    const send = (message: PageToolbarMessage): void => {
        setTimeout(() => listeners.forEach((listener) => listener(message)))
    }
    return {
        name: 'posthog-toolbar-page',
        postMessage: (message) => {
            const request = message as { type?: string; tool?: string; command?: { type: string; mode?: string } }
            if (request.type === 'start' && config) {
                send({ type: 'state', state: config.pageState })
            } else if (request.tool === 'session' && request.command?.type === 'set-mode') {
                send({ type: 'patch', patch: { mode: request.command.mode as PageToolbarState['mode'] } })
            }
        },
        disconnect: () => undefined,
        onMessage: { addListener: (listener) => listeners.push(listener), removeListener: () => undefined },
        onDisconnect: fakeEvent(),
    }
}

;(globalThis as unknown as { browser: unknown }).browser = {
    tabs: {
        query: async () => [{ id: 1, url: config?.tabUrl }],
        create: async () => ({ id: 2 }),
        remove: async () => undefined,
        connect: fakePort,
        sendMessage: async () => true,
        onActivated: fakeEvent(),
        onRemoved: fakeEvent(),
        onUpdated: fakeEvent(),
    },
    windows: { getCurrent: async () => ({ id: 1 }) },
    storage: {
        local: {
            get: async (key: string) => ({ [key]: config?.storage[key] }),
            set: async (items: Record<string, unknown>) => {
                Object.assign(config?.storage ?? {}, items)
            },
        },
    },
    scripting: { executeScript: async () => [{}] },
    runtime: { onMessage: fakeEvent(), onConnect: fakeEvent(), getURL: (path: string) => `/${path}` },
    permissions: {
        contains: async () => true,
        request: async () => true,
        getAll: async () => ({ origins: [] }),
        onAdded: fakeEvent(),
        onRemoved: fakeEvent(),
    },
    action: { onClicked: fakeEvent() },
}
