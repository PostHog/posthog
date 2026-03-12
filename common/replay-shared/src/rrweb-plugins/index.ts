import Hls from 'hls.js'

import { ReplayPlugin, playerConfig } from '@posthog/rrweb'

import { PLACEHOLDER_SVG_DATA_IMAGE_URL } from '../mobile/transformer/shared'

const PROXY_URL = 'https://replay.ph-proxy.com' as const

export const CorsPlugin: ReplayPlugin & {
    _replaceFontCssUrls: (value: string | null) => string | null
    _replaceFontUrl: (value: string) => string
    _replaceJSUrl: (value: string) => string
} = {
    _replaceFontCssUrls: (value: string | null): string | null => {
        return (
            value?.replace(
                /url\("(https:\/\/[^\s"?#]+\.(?:eot|woff2|ttf|woff)(?:[?#][^\s"]*)?)"\)/gi,
                `url("${PROXY_URL}/proxy?url=$1")`
            ) || null
        )
    },

    _replaceFontUrl: (value: string): string => {
        return value.replace(
            /^(https:\/\/[^\s"?#]+\.(?:eot|woff2|ttf|woff)(?:[?#][^\s"]*)?)$/i,
            `${PROXY_URL}/proxy?url=$1`
        )
    },

    _replaceJSUrl: (value: string): string => {
        return value.replace(/^(https:\/\/[^\s"?#]+\.js(?:[?#][^\s"]*)?)$/i, `${PROXY_URL}/proxy?url=$1`)
    },

    onBuild: (node) => {
        if (node.nodeName === 'STYLE') {
            const styleElement = node as HTMLStyleElement
            const childNodes = styleElement.childNodes
            for (let i = 0; i < childNodes.length; i++) {
                if (childNodes[i].nodeType == 3) {
                    const updatedContent = CorsPlugin._replaceFontCssUrls(childNodes[i].textContent)
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
                linkElement.href = CorsPlugin._replaceJSUrl(href)
            } else {
                linkElement.href = CorsPlugin._replaceFontUrl(href)
            }
        }

        if (node.nodeName === 'SCRIPT') {
            const scriptElement = node as HTMLScriptElement
            scriptElement.src = CorsPlugin._replaceJSUrl(scriptElement.src)
        }
    },
}

const defaultStyleRules = `.ph-no-capture { background-image: ${PLACEHOLDER_SVG_DATA_IMAGE_URL}; }`
const shopifyShorthandCSSFix =
    '@media (prefers-reduced-motion: no-preference) { .scroll-trigger:not(.scroll-trigger--offscreen).animate--slide-in { animation: var(--animation-slide-in) } }'

export const COMMON_REPLAYER_CONFIG: Partial<playerConfig> = {
    triggerFocus: false,
    insertStyleRules: [defaultStyleRules, shopifyShorthandCSSFix],
}

export { AudioMuteReplayerPlugin } from './audio-mute-plugin'
export { WindowTitlePlugin } from './window-title-plugin'

export const HLSPlayerPlugin: ReplayPlugin = {
    onBuild: (node) => {
        if (node && node.nodeName === 'VIDEO' && node.nodeType === 1) {
            const videoEl = node as HTMLVideoElement
            const hlsSrc = videoEl.getAttribute('hls-src')

            if (videoEl && hlsSrc) {
                if (Hls.isSupported()) {
                    const hls = new Hls()
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
                                    break
                            }
                        }
                    })
                } else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
                    videoEl.src = hlsSrc
                }
            }
        }
    },
}
