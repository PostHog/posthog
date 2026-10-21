import { checkUrlIsAuthorized } from 'lib/components/AuthorizedUrlList/authorizedUrlMatching'

import type { ToolbarEntitlementsApiEntitlements, UserApi } from '~/generated/core/api.schemas'

export type UnsupportedPageReason = 'browser-page' | 'insecure-page' | 'posthog-app' | 'extension-store'

export type SessionUserResult = { status: 'signed-in'; user: UserApi } | { status: 'signed-out' } | { status: 'error' }

export type ToolbarAccessResult =
    | { status: 'allowed'; entitlements: ToolbarEntitlementsApiEntitlements | null }
    | { status: 'denied' }
    | { status: 'signed-out' }
    | { status: 'error' }

export type ExtensionPanelState =
    | { kind: 'checking' }
    | { kind: 'unsupported-page'; reason: UnsupportedPageReason }
    | { kind: 'host-permission-needed' }
    | { kind: 'signed-out' }
    | { kind: 'no-toolbar-access' }
    | { kind: 'unauthorized-url'; origin: string }
    | { kind: 'error' }
    | { kind: 'ready'; origin: string }

export interface ExtensionPanelInputs {
    /** `undefined` while the active tab is still being read. */
    tabUrl: string | null | undefined
    uiHost: string
    /** `null` while the permission check is pending. */
    hostPermission: boolean | null
    /** `null` while the session loads. */
    sessionStatus: SessionUserResult['status'] | null
    toolbarAccess: ToolbarAccessResult | null
    /** The project's authorized URLs, `null` while they load. */
    authorizedUrls: string[] | 'error' | null
}

// Browsers block every extension from scripting their own add-on stores.
const EXTENSION_STORE_HOSTNAMES = new Set(['chromewebstore.google.com', 'chrome.google.com', 'addons.mozilla.org'])

const LOOPBACK_HOSTNAMES = new Set(['localhost', '127.0.0.1', '[::1]'])

/** Mirrors the toolbar OAuth rules: http(s) only, and plain http only on loopback hosts. */
function unsupportedPageReason(tabUrl: string | null, uiHost: string): UnsupportedPageReason | null {
    if (!tabUrl) {
        return 'browser-page'
    }
    let parsed: URL
    try {
        parsed = new URL(tabUrl)
    } catch {
        return 'browser-page'
    }
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
        return 'browser-page'
    }
    if (parsed.protocol === 'http:' && !LOOPBACK_HOSTNAMES.has(parsed.hostname)) {
        return 'insecure-page'
    }
    if (EXTENSION_STORE_HOSTNAMES.has(parsed.hostname)) {
        return 'extension-store'
    }
    if (parsed.origin === uiHost) {
        return 'posthog-app'
    }
    return null
}

export function getExtensionPanelState(inputs: ExtensionPanelInputs): ExtensionPanelState {
    if (inputs.tabUrl === undefined) {
        return { kind: 'checking' }
    }
    const reason = unsupportedPageReason(inputs.tabUrl, inputs.uiHost)
    if (reason || !inputs.tabUrl) {
        return { kind: 'unsupported-page', reason: reason ?? 'browser-page' }
    }
    const origin = new URL(inputs.tabUrl).origin

    if (inputs.hostPermission === null) {
        return { kind: 'checking' }
    }
    if (!inputs.hostPermission) {
        return { kind: 'host-permission-needed' }
    }

    if (!inputs.sessionStatus) {
        return { kind: 'checking' }
    }
    if (inputs.sessionStatus === 'signed-out') {
        return { kind: 'signed-out' }
    }
    if (inputs.sessionStatus === 'error') {
        return { kind: 'error' }
    }

    if (!inputs.toolbarAccess) {
        return { kind: 'checking' }
    }
    if (inputs.toolbarAccess.status === 'signed-out') {
        return { kind: 'signed-out' }
    }
    if (inputs.toolbarAccess.status === 'denied') {
        return { kind: 'no-toolbar-access' }
    }
    if (inputs.toolbarAccess.status === 'error') {
        return { kind: 'error' }
    }

    if (inputs.authorizedUrls === null) {
        return { kind: 'checking' }
    }
    if (inputs.authorizedUrls === 'error') {
        return { kind: 'error' }
    }
    if (!checkUrlIsAuthorized(inputs.tabUrl, inputs.authorizedUrls)) {
        return { kind: 'unauthorized-url', origin }
    }
    return { kind: 'ready', origin }
}
