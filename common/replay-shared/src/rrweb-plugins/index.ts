import { ReplayPlugin, playerConfig } from 'posthog-js/rrweb'

import { PLACEHOLDER_SVG_DATA_IMAGE_URL } from '../mobile/transformer/shared'

const PROXY_URL = 'https://replay.ph-proxy.com' as const

type CorsReplayPlugin = ReplayPlugin & {
    _replaceFontCssUrls: (value: string | null) => string | null
    _replaceFontUrl: (value: string) => string
    _replaceJSUrl: (value: string) => string
}

// The token goes before `url`, because a font url can end in a `#` fragment, and the browser
// does not send anything after a `#` to the proxy.
function proxyUrl(targetUrl: string, token: string | null | undefined): string {
    return token
        ? `${PROXY_URL}/proxy?token=${encodeURIComponent(token)}&url=${targetUrl}`
        : `${PROXY_URL}/proxy?url=${targetUrl}`
}

// getProxyToken runs for every url, so a token that the player refreshes reaches nodes it builds later.
export function createCorsPlugin(getProxyToken: () => string | null | undefined): CorsReplayPlugin {
    const plugin: CorsReplayPlugin = {
        _replaceFontCssUrls: (value: string | null): string | null => {
            return (
                value?.replace(
                    /url\("(https:\/\/[^\s"?#]+\.(?:eot|woff2|ttf|woff)(?:[?#][^\s"]*)?)"\)/gi,
                    (_, targetUrl: string) => `url("${proxyUrl(targetUrl, getProxyToken())}")`
                ) || null
            )
        },

        _replaceFontUrl: (value: string): string => {
            return value.replace(/^(https:\/\/[^\s"?#]+\.(?:eot|woff2|ttf|woff)(?:[?#][^\s"]*)?)$/i, (targetUrl) =>
                proxyUrl(targetUrl, getProxyToken())
            )
        },

        _replaceJSUrl: (value: string): string => {
            return value.replace(/^(https:\/\/[^\s"?#]+\.js(?:[?#][^\s"]*)?)$/i, (targetUrl) =>
                proxyUrl(targetUrl, getProxyToken())
            )
        },

        onBuild: (node) => {
            if (node.nodeName === 'STYLE') {
                const styleElement = node as HTMLStyleElement
                const childNodes = styleElement.childNodes
                for (let i = 0; i < childNodes.length; i++) {
                    if (childNodes[i].nodeType == 3) {
                        const updatedContent = plugin._replaceFontCssUrls(childNodes[i].textContent)
                        if (updatedContent !== childNodes[i].textContent) {
                            childNodes[i].textContent = updatedContent
                        }
                    }
                }
            }

            if (node.nodeName === 'LINK') {
                const linkElement = node as HTMLLinkElement
                const href = linkElement.href
                if (!href) {
                    return
                }
                if (linkElement.getAttribute('rel') == 'modulepreload') {
                    linkElement.href = plugin._replaceJSUrl(href)
                } else {
                    linkElement.href = plugin._replaceFontUrl(href)
                }
            }

            if (node.nodeName === 'SCRIPT') {
                const scriptElement = node as HTMLScriptElement
                scriptElement.src = plugin._replaceJSUrl(scriptElement.src)
            }
        },
    }
    return plugin
}

// The headless renderer has no proxy token, so it calls the proxy without one.
export const CorsPlugin = createCorsPlugin(() => null)

export const BLOCKED_ELEMENT_LABEL = 'Hidden from recording by privacy settings'

function blockedElementLabelImage(text: string): string {
    // The viewBox lets the label shrink to fit a small element while keeping its proportions.
    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="40" viewBox="0 0 400 40">` +
        `<rect x="1" y="1" width="398" height="38" rx="6" fill="#ffffff" stroke="#6b7280"/>` +
        `<text x="200" y="26" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#374151">${text}</text>` +
        `</svg>`
    return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`
}

// Without the label, viewers read the stripes as a broken or loading element.
const defaultStyleRules = `.ph-no-capture {
    background-image: ${blockedElementLabelImage(BLOCKED_ELEMENT_LABEL)}, ${PLACEHOLDER_SVG_DATA_IMAGE_URL};
    background-position: center, 0 0;
    background-size: min(400px, 90%) min(40px, 90%), auto;
    background-repeat: no-repeat, repeat;
}`
const shopifyShorthandCSSFix =
    '@media (prefers-reduced-motion: no-preference) { .scroll-trigger:not(.scroll-trigger--offscreen).animate--slide-in { animation: var(--animation-slide-in) } }'
// Language picker prepended to <body> by the "Translator, dictionary - accurate translate" extension.
// Its hiding CSS is content-script-only, so unrecordable; without this the picker reflows the page.
const translatorExtensionPopupFix =
    'body > div.translate-tooltip-mtz, body > span.translate-button-mtz { display: none !important; }'

export const COMMON_REPLAYER_CONFIG: Partial<playerConfig> = {
    triggerFocus: false,
    insertStyleRules: [defaultStyleRules, shopifyShorthandCSSFix, translatorExtensionPopupFix],
    // Keep the replay iframe scriptless. UNSAFE_replayCanvas makes rrweb add `allow-scripts`
    // to the sandbox, which combined with the required `allow-same-origin` lets untrusted
    // recorded content escape the sandbox into the app origin. Canvas is replayed via
    // CanvasReplayerPlugin instead, which needs no in-frame scripting.
    UNSAFE_replayCanvas: false,
}

/**
 * rrweb does not speed CSS animations and transitions up with playback, so at high speeds they run behind the page.
 * Snap them to their end state instead: removing them outright leaves content a keyframe reveals stuck at opacity 0.
 */
export function speedDependentStyleRules(speed: number): string[] {
    return speed >= 2
        ? [
              '*, *::before, *::after { animation-duration: 1ms !important; animation-delay: 0s !important; animation-iteration-count: 1 !important; animation-fill-mode: forwards !important; transition-duration: 0s !important; transition-delay: 0s !important; }',
          ]
        : []
}

export { AudioMuteReplayerPlugin } from './audio-mute-plugin'
export { WindowTitlePlugin } from './window-title-plugin'

export function createHLSPlayerPlugin(): ReplayPlugin & { destroy: () => void } {
    const instances: Set<{ destroy: () => void }> = new Set()
    let destroyed = false

    return {
        onBuild: (node) => {
            if (node && node.nodeName === 'VIDEO' && node.nodeType === 1) {
                const videoEl = node as HTMLVideoElement
                const hlsSrc = videoEl.getAttribute('hls-src')

                if (videoEl && hlsSrc) {
                    void import('hls.js')
                        .then(({ default: Hls }) => {
                            if (destroyed) {
                                return
                            }
                            if (Hls.isSupported()) {
                                const hls = new Hls()
                                instances.add(hls)
                                hls.loadSource(hlsSrc)
                                hls.attachMedia(videoEl)

                                hls.on(Hls.Events.ERROR, (_, data) => {
                                    if (data.fatal) {
                                        switch (data.type) {
                                            case Hls.ErrorTypes.NETWORK_ERROR:
                                                hls.startLoad()
                                                break
                                            case Hls.ErrorTypes.MEDIA_ERROR:
                                                hls.recoverMediaError()
                                                break
                                            default:
                                                hls.destroy()
                                                instances.delete(hls)
                                                break
                                        }
                                    }
                                })
                            } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
                                videoEl.src = hlsSrc
                            }
                        })
                        .catch(() => {
                            // Chunk load failure — fall back to native HLS if the browser supports it
                            if (destroyed) {
                                return
                            }
                            if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
                                videoEl.src = hlsSrc
                            }
                        })
                }
            }
        },

        destroy: () => {
            destroyed = true

            for (const hls of instances) {
                hls.destroy()
            }
            instances.clear()
        },
    }
}

/** @deprecated Use createHLSPlayerPlugin() for proper lifecycle management */
export const HLSPlayerPlugin: ReplayPlugin = createHLSPlayerPlugin()
