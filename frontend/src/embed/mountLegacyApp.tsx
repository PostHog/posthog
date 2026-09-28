import '~/styles'
import './embed.scss'

import '../buffer-polyfill'
// The relative path keeps this with the side-effect imports when imports are sorted, so it evaluates
// before any module that builds a zod schema. See lib/configureZod.
import '../lib/configureZod'

import { createRoot } from 'react-dom/client'

import { setEmbedContext } from 'lib/embed/embedContext'
import { setExternalSessionProvider } from 'lib/oauth/oauthClient'

import { initKea } from '~/initKea'

import { EmbeddedApp } from './EmbeddedApp'
import { buildEmbeddedPreflight } from './embeddedPreflight'
import { createEmbedRouterBinding, syncRouterFromHost } from './embedRouter'
import { EMBED_API_VERSION, EmbedHandle, EmbedHost } from './embedTypes'
import { initEmbeddedPostHog } from './initEmbeddedPostHog'

// pinned: matches the root class in embed.scss and the rootClass build.mjs scopes the stylesheet to.
const EMBED_ROOT_CLASS = 'ph-embed'

let mounted = false

/**
 * Renders the web app into `element` inside another app's page. The host owns the URL, the session and
 * the theme. The bundle's stylesheet is scoped to `element`, and this function attaches it to the page.
 *
 * Only one instance can run per page, because kea keeps one global context and `initKea` resets it.
 */
export function mountLegacyApp(element: HTMLElement, host: EmbedHost): EmbedHandle {
    if (mounted) {
        throw new Error('The PostHog web app is already mounted on this page.')
    }
    mounted = true

    const stylesheet = document.createElement('link')
    stylesheet.rel = 'stylesheet'
    stylesheet.href = new URL('embed.css', import.meta.url).href
    document.head.appendChild(stylesheet)

    element.classList.add(EMBED_ROOT_CLASS)
    setExternalSessionProvider({
        getSession: () => ({
            backendHost: host.backendHost,
            clientId: '',
            accessToken: host.getAccessToken(),
            refreshToken: '',
            expiresAt: Number.MAX_SAFE_INTEGER,
        }),
        refresh: () => host.refreshAccessToken(),
    })
    setEmbedContext({
        root: element,
        preflight: buildEmbeddedPreflight(host.backendHost),
        signOut: () => host.signOut(),
    })
    initEmbeddedPostHog(host.analytics)

    const { history, location } = createEmbedRouterBinding(host)
    initKea({ routerHistory: history, routerLocation: location, replaceInitialPathInWindow: false })

    const reactRoot = createRoot(element)
    let theme = host.theme
    const render = (): void => reactRoot.render(<EmbeddedApp theme={theme} onSignOut={() => host.signOut()} />)
    render()

    return {
        apiVersion: EMBED_API_VERSION,
        syncLocation: () => syncRouterFromHost(host),
        setTheme: (nextTheme) => {
            theme = nextTheme
            render()
        },
        unmount: () => {
            reactRoot.unmount()
            stylesheet.remove()
            element.classList.remove(EMBED_ROOT_CLASS)
            element.removeAttribute('theme')
            setEmbedContext(null)
            setExternalSessionProvider(null)
            mounted = false
        },
    }
}
