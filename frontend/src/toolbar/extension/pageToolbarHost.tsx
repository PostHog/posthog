import { getContext } from 'kea'
import { Root, createRoot } from 'react-dom/client'

import { ElementOverlays } from '~/toolbar/elements/ElementOverlays'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { ToolbarProps } from '~/types'

import { ExtensionPort, extensionFileUrl, onPageToolbarConnect } from './extensionBrowser'
import { extensionPageToolbarLogic, getPageToolbarState } from './extensionPageToolbarLogic'
import { PageToolbarMessage, PageToolbarSession, PageToolbarState, isPageToolbarRequest } from './pageToolbarBridge'

const STATE_POST_INTERVAL_MS = 100

// A reload or a quick reopen of the panel keeps the page tools, and their loaded data, for this long.
const IDLE_STOP_MS = 30 * 1000

function PageToolbarOverlays(): JSX.Element {
    return (
        // The toolbar stylesheet scopes its colors to a theme attribute.
        // eslint-disable-next-line react/no-unknown-property
        <div {...{ theme: 'light' }}>
            <ElementOverlays showHeatmapCanvas={false} />
        </div>
    )
}

export class PageToolbarHost {
    private uiHost: string | null = null
    private unmountLogics: (() => void) | null = null
    private overlayRoot: Root | null = null
    private ports = new Set<ExtensionPort>()
    private lastState: PageToolbarState | null = null
    private lastAccessToken: string | null = null
    private postTimeout: ReturnType<typeof setTimeout> | null = null
    private idleTimeout: ReturnType<typeof setTimeout> | null = null

    constructor(
        private readonly shadowRoot: ShadowRoot,
        private readonly resetLogics: () => void
    ) {}

    listen(): void {
        onPageToolbarConnect((port) => this.addPort(port))
    }

    private addPort(port: ExtensionPort): void {
        this.ports.add(port)
        this.clearIdleTimeout()
        port.onMessage.addListener((message) => {
            if (!isPageToolbarRequest(message)) {
                return
            }
            if ('tool' in message) {
                if (this.unmountLogics) {
                    extensionPageToolbarLogic.actions.handleCommand(message)
                }
                return
            }
            this.start(message.session, message.href)
            this.postFullState(port)
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

    private start(session: PageToolbarSession, href: string): void {
        if (this.unmountLogics && this.uiHost === session.uiHost) {
            toolbarConfigLogic.actions.setOAuthTokens(session.accessToken, session.refreshToken, session.clientId)
            extensionPageToolbarLogic.actions.handleCommand({ tool: 'session', command: { type: 'set-href', href } })
            return
        }
        this.stop()
        const props: ToolbarProps = {
            source: 'extension',
            uiHost: session.uiHost,
            accessToken: session.accessToken,
            refreshToken: session.refreshToken ?? undefined,
            clientId: session.clientId,
            dataAttributes: session.dataAttributes,
        }
        const unsubscribe = getContext().store.subscribe(() => this.scheduleStatePost())
        const unmountConfig = toolbarConfigLogic(props).mount()
        const unmountPageToolbar = extensionPageToolbarLogic.mount()
        this.unmountLogics = () => {
            unsubscribe()
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
        this.uiHost = null
        this.lastState = null
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
    }

    private broadcast(message: PageToolbarMessage): void {
        for (const port of this.ports) {
            port.postMessage(message)
        }
    }
}
