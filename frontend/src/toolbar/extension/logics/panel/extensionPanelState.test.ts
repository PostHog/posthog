import { ExtensionPanelInputs, getExtensionPanelState } from './extensionPanelState'

const READY_INPUTS: ExtensionPanelInputs = {
    tabUrl: 'https://www.example.com/pricing',
    uiHost: 'https://us.posthog.com',
    hostPermission: true,
    sessionStatus: 'signed-in',
    toolbarAccess: { status: 'allowed', entitlements: { toolbar_heatmaps: true } },
    authorizedUrls: ['https://example.com'],
}

describe('getExtensionPanelState', () => {
    test.each<[string, Partial<ExtensionPanelInputs>, ReturnType<typeof getExtensionPanelState>]>([
        ['authorized page', {}, { kind: 'ready', origin: 'https://www.example.com' }],
        ['tab not read yet', { tabUrl: undefined }, { kind: 'checking' }],
        ['browser page', { tabUrl: 'chrome://extensions' }, { kind: 'unsupported-page', reason: 'browser-page' }],
        ['no tab url', { tabUrl: null }, { kind: 'unsupported-page', reason: 'browser-page' }],
        [
            'plain http on a public host',
            { tabUrl: 'http://example.com' },
            { kind: 'unsupported-page', reason: 'insecure-page' },
        ],
        [
            'plain http on loopback',
            { tabUrl: 'http://localhost:3000/', authorizedUrls: ['http://localhost:3000'] },
            { kind: 'ready', origin: 'http://localhost:3000' },
        ],
        [
            'extension store',
            { tabUrl: 'https://addons.mozilla.org/en-US/firefox/' },
            { kind: 'unsupported-page', reason: 'extension-store' },
        ],
        [
            'the PostHog app itself',
            { tabUrl: 'https://us.posthog.com/project/1' },
            { kind: 'unsupported-page', reason: 'posthog-app' },
        ],
        [
            'unsupported page wins over a missing session',
            { tabUrl: 'about:blank', sessionStatus: 'signed-out' },
            { kind: 'unsupported-page', reason: 'browser-page' },
        ],
        ['host permission pending', { hostPermission: null }, { kind: 'checking' }],
        ['host permission missing', { hostPermission: false }, { kind: 'host-permission-needed' }],
        ['session loading', { sessionStatus: null }, { kind: 'checking' }],
        ['signed out', { sessionStatus: 'signed-out' }, { kind: 'signed-out' }],
        [
            'session expired before the access check',
            { toolbarAccess: { status: 'signed-out' } },
            { kind: 'signed-out' },
        ],
        ['session request failed', { sessionStatus: 'error' }, { kind: 'error' }],
        ['toolbar access loading', { toolbarAccess: null }, { kind: 'checking' }],
        ['toolbar access denied', { toolbarAccess: { status: 'denied' } }, { kind: 'no-toolbar-access' }],
        ['authorized URLs loading', { authorizedUrls: null }, { kind: 'checking' }],
        ['authorized URLs failed', { authorizedUrls: 'error' }, { kind: 'error' }],
        [
            'page not in authorized URLs',
            { authorizedUrls: ['https://example.co'] },
            { kind: 'unauthorized-url', origin: 'https://www.example.com' },
        ],
        [
            'access denial wins over an unauthorized page',
            { toolbarAccess: { status: 'denied' }, authorizedUrls: [] },
            { kind: 'no-toolbar-access' },
        ],
    ])('%s', (_, overrides, expected) => {
        expect(getExtensionPanelState({ ...READY_INPUTS, ...overrides })).toEqual(expected)
    })
})
