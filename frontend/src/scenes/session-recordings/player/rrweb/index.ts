import { playerConfig, ReplayPlugin } from '@posthog/rrweb'
import { EventType, eventWithTime, IncrementalSource } from '@posthog/rrweb-types'
import Hls from 'hls.js'

export const PLACEHOLDER_SVG_DATA_IMAGE_URL =
    'url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg==");'

const PROXY_URL = 'https://replay.ph-proxy.com' as const

export const CorsPlugin: ReplayPlugin & {
    _replaceFontCssUrls: (value: string | null) => string | null
    _replaceFontUrl: (value: string) => string
    _replaceJSUrl: (value: string) => string
} = {
    _replaceFontCssUrls: (value: string | null): string | null => {
        return (
            value?.replace(
                /url\("(https:\/\/\S*(?:\.eot|\.woff2|\.ttf|\.woff)\S*)"\)/gi,
                `url("${PROXY_URL}/proxy?url=$1")`
            ) || null
        )
    },

    _replaceFontUrl: (value: string): string => {
        return value.replace(/^(https:\/\/\S*(?:\.eot|\.woff2|\.ttf|\.woff)\S*)$/i, `${PROXY_URL}/proxy?url=$1`)
    },

    _replaceJSUrl: (value: string): string => {
        return value.replace(/^(https:\/\/\S*(?:\.js)\S*)$/i, `${PROXY_URL}/proxy?url=$1`)
    },

    onBuild: (node) => {
        if (node.nodeName === 'STYLE') {
            const styleElement = node as HTMLStyleElement
            const childNodes = styleElement.childNodes
            for (let i = 0; i < childNodes.length; i++) {
                // not every node in a style element is text
                // e.g. formatted text might cause some <br/> elements to be present
                // separating lines of text
                if (childNodes[i].nodeType == 3) {
                    // then this is a text node
                    // TODO what about CSS import URLs we could replace those too?
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

export type Node = {
    id: number
    type: number
    tagName: string
    childNodes: Node[]
    textContent?: string
}

export const WindowTitlePlugin = (cb: (windowId: string, title: string) => void): ReplayPlugin => {
    const titleElementIds = new Set<number>()

    const extractTitleTextEl = (node: Node): Node | undefined => {
        // Document node
        if (node.type === 0) {
            const el = node.childNodes.find((n) => n.type === 2) // element node

            if (el) {
                const headEl = el.childNodes.filter((n) => n.type === 2).find((n) => n.tagName === 'head')

                if (headEl) {
                    const titleEl = headEl.childNodes.filter((n) => n.type === 2).find((n) => n.tagName === 'title')

                    if (titleEl) {
                        const textEl = titleEl.childNodes.find((n) => n.type === 3) // text node
                        return textEl
                    }
                }
            }
        }
    }

    return {
        // eslint-disable-next-line @typescript-eslint/no-misused-promises
        handler: async (e: eventWithTime, isSync) => {
            if ('windowId' in e && e.windowId && isSync) {
                const windowId = e.windowId as string
                if (e.type === EventType.FullSnapshot) {
                    titleElementIds.clear()
                    const el = extractTitleTextEl(e.data.node as Node)
                    if (windowId && el && el.textContent) {
                        titleElementIds.add(el.id)
                        cb(windowId, el.textContent)
                    }
                } else if (e.type === EventType.IncrementalSnapshot && e.data.source === IncrementalSource.Mutation) {
                    e.data.texts.forEach(({ id, value }) => {
                        if (titleElementIds.has(id) && value) {
                            cb(windowId, value)
                        }
                    })
                }
            }
        },
    }
}

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
                                // Unrecoverable error
                                default:
                                    hls.destroy()
                                    break
                            }
                        }
                    })
                }
                // HLS not supported natively but can play in Safari
                else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
                    videoEl.src = hlsSrc
                }
            }
        }
    },
}

const defaultStyleRules = `.ph-no-capture { background-image: ${PLACEHOLDER_SVG_DATA_IMAGE_URL} }`
// replaces a common rule in Shopify templates removed during capture
// fix tracked in https://github.com/rrweb-io/rrweb/pull/1322
const shopifyShorthandCSSFix =
    '@media (prefers-reduced-motion: no-preference) { .scroll-trigger:not(.scroll-trigger--offscreen).animate--slide-in { animation: var(--animation-slide-in) } }'

export type LogType = 'log' | 'warning'
export type LoggingTimers = Record<LogType, NodeJS.Timeout | null>
export type BuiltLogging = {
    logger: playerConfig['logger']
    timers: LoggingTimers
}

export const makeNoOpLogger = (): BuiltLogging => {
    return {
        logger: {
            log: () => {},
            warn: () => {},
        },
        timers: { log: null, warning: null },
    }
}

export const makeLogger = (onIncrement: (count: number) => void): BuiltLogging => {
    const counters = {
        log: 0,
        warning: 0,
    }

    ;(window as any)[`__posthog_player_logs`] = (window as any)[`__posthog_player_logs`] || []
    ;(window as any)[`__posthog_player_warnings`] = (window as any)[`__posthog_player_warnings`] || []

    const logStores: Record<LogType, any[]> = {
        log: (window as any)[`__posthog_player_logs`],
        warning: (window as any)[`__posthog_player_warnings`],
    }

    const timers: LoggingTimers = {
        log: null,
        warning: null,
    }

    const logger = (type: LogType): ((message?: any, ...optionalParams: any[]) => void) => {
        // NOTE: RRWeb can log _alot_ of warnings,
        // so we debounce the count otherwise we just end up making the performance worse
        // We also don't log the messages directly.
        // Sometimes the sheer size of messages and warnings can cause the browser to crash deserializing it all

        return (...args: any[]): void => {
            logStores[type].push(args)
            counters[type] += 1

            if (!timers[type]) {
                timers[type] = setTimeout(() => {
                    timers[type] = null
                    if (type === 'warning') {
                        onIncrement(logStores[type].length)
                    }

                    console.warn(
                        `[PostHog Replayer] ${counters[type]} ${type}s (window.__posthog_player_${type}s to safely log them)`
                    )
                    counters[type] = 0
                }, 5000)
            }
        }
    }

    return {
        logger: {
            log: logger('log'),
            warn: logger('warning'),
        },
        timers,
    }
}

export const COMMON_REPLAYER_CONFIG: Partial<playerConfig> = {
    triggerFocus: false,
    insertStyleRules: [defaultStyleRules, shopifyShorthandCSSFix],
}
