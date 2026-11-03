import { getContext } from 'kea'
import { Root, createRoot } from 'react-dom/client'

import { ElementOverlays } from '~/toolbar/shared/elements/ElementOverlays'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { ToolbarProps } from '~/types'

import { ExtensionPort, extensionFileUrl, onPageToolbarConnect } from '../../browser/extensionBrowser'
import { extensionPageExperimentsLogic } from '../../logics/page/extensionPageExperimentsLogic'
import { extensionPageFlagsLogic } from '../../logics/page/extensionPageFlagsLogic'
import { extensionPageMoreLogic } from '../../logics/page/extensionPageMoreLogic'
import { extensionPageToolbarLogic, getPageToolbarState } from '../../logics/page/extensionPageToolbarLogic'
import { PagePosthogBridge, onPagePosthogAppeared, requestPageAnalytics } from '../../messaging/pagePosthogBridge'
import {
    PageToolbarMessage,
    PageToolbarMode,
    PageToolbarSession,
    PageToolbarState,
    isPageToolbarRequest,
} from '../../messaging/pageToolbarBridge'

const STATE_POST_INTERVAL_MS = 100

// A reload or a quick reopen of the panel keeps the page tools, and their loaded data, for this long.
const IDLE_STOP_MS = 30 * 1000

function PageToolbarOverlays(): JSX.Element {
    return (
        // The toolbar stylesheet scopes its colors to a theme attribute.
        // eslint-disable-next-line react/no-unknown-property
        <div {...{ theme: 'light' }}>
            <ElementOverlays showHeatmapCanvas />
        </div>
    )
}

export class PageToolbarHost {
    private session: { session: PageToolbarSession; href: string } | null = null
    private uiHost: string | null = null
    private posthogBridge: PagePosthogBridge | null = null
    private unmountLogics: (() => void) | null = null
    private overlayRoot: Root | null = null
    private ports = new Set<ExtensionPort>()
    private lastState: PageToolbarState | null = null
    private lastScreenshotPreview: string | null = null
    private lastAccessToken: string | null = null
    private postTimeout: ReturnType<typeof setTimeout> | null = null
    private idleTimeout: ReturnType<typeof setTimeout> | null = null
    private starting: Promise<void> | null = null

    constructor(
        private readonly shadowRoot: ShadowRoot,
        private readonly resetLogics: () => void
    ) {}

    listen(): void {
        onPageToolbarConnect((port) => this.addPort(port))
        // A page that loads posthog-js after the page tools started gets them again with the page's posthog-js.
        onPagePosthogAppeared(() => {
            const current = this.session
            if (this.unmountLogics && !this.posthogBridge && current) {
                const { mode } = extensionPageToolbarLogic.values
                this.stop()
                this.queueStart(current.session, current.href, [...this.ports], mode)
            }
        })
    }

    private addPort(port: ExtensionPort): void {
        this.ports.add(port)
        this.clearIdleTimeout()
        port.onMessage.addListener((message) => {
            if (!isPageToolbarRequest(message)) {
                return
            }
            if ('tool' in message) {
                void this.starting?.then(() => {
                    if (this.unmountLogics) {
                        extensionPageToolbarLogic.actions.handleCommand(message)
                    }
                })
                return
            }
            this.queueStart(message.session, message.href, [port])
        })
        port.onDisconnect.addListener(() => {
            this.ports.delete(port)
            if (this.ports.size === 0 && this.unmountLogics) {
                // Without a panel nobody can turn the page tools off, so they stop with the last panel.
                extensionPageToolbarLogic.actions.setMode('none')
                this.idleTimeout = setTimeout(() => this.stop(), IDLE_STOP_MS)
            }
        })
    }

    /** Starts run one after another, so two panels connecting at once can't mount the page tools twice. */
    private queueStart(
        session: PageToolbarSession,
        href: string,
        ports: ExtensionPort[],
        mode?: PageToolbarMode
    ): void {
        this.starting = (this.starting ?? Promise.resolve())
            .then(() => this.start(session, href))
            .then(() => {
                if (mode && mode !== 'none') {
                    extensionPageToolbarLogic.actions.setMode(mode)
                }
                ports.forEach((port) => this.postFullState(port))
            })
    }

    private async start(session: PageToolbarSession, href: string): Promise<void> {
        this.session = { session, href }
        if (this.unmountLogics && this.uiHost === session.uiHost) {
            toolbarConfigLogic.actions.setOAuthTokens(session.accessToken, session.refreshToken, session.clientId)
            extensionPageToolbarLogic.actions.handleCommand({ tool: 'session', command: { type: 'set-href', href } })
            return
        }
        this.stop()
        const pageAnalytics = await requestPageAnalytics()
        this.posthogBridge = pageAnalytics
            ? new PagePosthogBridge(pageAnalytics, (status) =>
                  extensionPageFlagsLogic.findMounted()?.actions.setFlagMutationStatus(status)
              )
            : null
        const props: ToolbarProps = {
            source: 'extension',
            uiHost: session.uiHost,
            accessToken: session.accessToken,
            refreshToken: session.refreshToken ?? undefined,
            clientId: session.clientId,
            dataAttributes: session.dataAttributes,
            posthog: this.posthogBridge?.posthog,
        }
        const unsubscribe = getContext().store.subscribe(() => this.scheduleStatePost())
        const unmountConfig = toolbarConfigLogic(props).mount()
        const unmountPageToolbar = extensionPageToolbarLogic({ posthogBridge: this.posthogBridge }).mount()
        const unmountMore = extensionPageMoreLogic({ posthogBridge: this.posthogBridge }).mount()
        this.unmountLogics = () => {
            unsubscribe()
            unmountMore()
            unmountPageToolbar()
            unmountConfig()
            // The toolbar mounts some logics for good, and they keep toolbarConfigLogic with the last session's props
            // mounted. A fresh context makes the next start use the new host and tokens.
            this.resetLogics()
        }
        this.uiHost = session.uiHost
        this.lastAccessToken = session.accessToken
        extensionPageToolbarLogic.actions.handleCommand({ tool: 'session', command: { type: 'set-href', href } })
        this.renderOverlays()
    }

    private stop(): void {
        // A restart and a host change both stop the tools, and the page must not keep a variant preview.
        extensionPageExperimentsLogic.findMounted()?.actions.closeExperiments()
        this.clearIdleTimeout()
        if (this.postTimeout !== null) {
            clearTimeout(this.postTimeout)
            this.postTimeout = null
        }
        this.shadowRoot
            .querySelectorAll(`link[href="${extensionFileUrl('content.css')}"]`)
            .forEach((link) => link.remove())
        this.overlayRoot?.unmount()
        this.overlayRoot = null
        this.unmountLogics?.()
        this.unmountLogics = null
        this.posthogBridge?.dispose()
        this.posthogBridge = null
        this.uiHost = null
        this.lastState = null
        this.lastScreenshotPreview = null
    }

    private clearIdleTimeout(): void {
        if (this.idleTimeout !== null) {
            clearTimeout(this.idleTimeout)
            this.idleTimeout = null
        }
    }

    private renderOverlays(): void {
        const stylesheet = document.createElement('link')
        stylesheet.rel = 'stylesheet'
        stylesheet.href = extensionFileUrl('content.css')
        const container = document.createElement('div')
        const overlayRoot = createRoot(container)
        this.overlayRoot = overlayRoot
        // heatmap.js sizes its canvas once, when it mounts, so the overlays wait for the stylesheet that sizes them.
        const render = (): void => {
            if (this.overlayRoot === overlayRoot) {
                overlayRoot.render(<PageToolbarOverlays />)
            }
        }
        stylesheet.addEventListener('load', render, { once: true })
        stylesheet.addEventListener('error', render, { once: true })
        this.shadowRoot.append(stylesheet, container)
    }

    private scheduleStatePost(): void {
        if (this.postTimeout === null && this.unmountLogics && this.ports.size > 0) {
            this.postTimeout = setTimeout(() => {
                this.postTimeout = null
                this.postChanges()
            }, STATE_POST_INTERVAL_MS)
        }
    }

    /** A new panel gets every slice, the other panels keep getting patches. */
    private postFullState(port: ExtensionPort): void {
        if (!this.unmountLogics) {
            return
        }
        const state = getPageToolbarState()
        this.lastState = state
        port.postMessage({ type: 'state', state } satisfies PageToolbarMessage)
        const preview = this.screenshotPreview()
        if (preview) {
            port.postMessage({ type: 'screenshot-preview', dataUrl: preview } satisfies PageToolbarMessage)
        }
    }

    private postChanges(): void {
        if (!this.unmountLogics) {
            return
        }
        const { accessToken, refreshToken, clientId } = toolbarConfigLogic.values
        if (accessToken !== this.lastAccessToken) {
            this.lastAccessToken = accessToken
            this.broadcast(
                accessToken && clientId
                    ? { type: 'tokens', tokens: { accessToken, refreshToken, clientId } }
                    : { type: 'token-expired' }
            )
        }
        const state = getPageToolbarState()
        const previous = this.lastState
        this.lastState = state
        const patch = Object.fromEntries(
            (Object.keys(state) as (keyof PageToolbarState)[])
                .filter((slice) => !previous || state[slice] !== previous[slice])
                .map((slice) => [slice, state[slice]])
        ) as Partial<PageToolbarState>
        if (Object.keys(patch).length > 0) {
            this.broadcast({ type: 'patch', patch })
        }
        const preview = this.screenshotPreview()
        if (preview && preview !== this.lastScreenshotPreview) {
            this.broadcast({ type: 'screenshot-preview', dataUrl: preview })
        }
        this.lastScreenshotPreview = preview
    }

    private screenshotPreview(): string | null {
        return extensionPageMoreLogic.findMounted()?.values.screenshotPreview ?? null
    }

    private broadcast(message: PageToolbarMessage): void {
        for (const port of this.ports) {
            port.postMessage(message)
        }
    }
}
