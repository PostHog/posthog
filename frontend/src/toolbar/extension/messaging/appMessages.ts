// Messages the PostHog app sends to the extension through `externally_connectable`. The app and the extension ship
// separately, so a new app build talks to older installs: add message types, and never change these.

// pinned: wire protocol between the PostHog app and published extension versions
export const APP_MESSAGE_PING = 'posthog-toolbar-extension:ping'
// pinned: wire protocol between the PostHog app and published extension versions
export const APP_MESSAGE_OPEN_URL = 'posthog-toolbar-extension:open-url'

export type AppMessage = { type: typeof APP_MESSAGE_PING } | { type: typeof APP_MESSAGE_OPEN_URL; url: string }

export interface PingResponse {
    installed: true
}

export interface OpenUrlResponse {
    opened: boolean
    /** Chrome opens the side panel only in response to a user action, which a message from a page may not count as. */
    panelOpened: boolean
}
