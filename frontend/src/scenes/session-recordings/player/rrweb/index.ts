import { playerConfig, ReplayPlugin } from 'rrweb/typings/types'

const PROXY_URL = 'https://replay.ph-proxy.com' as const

export const CorsPlugin: ReplayPlugin & {
    _replaceFontCssUrls: (value: string | null) => string | null
    _replaceFontUrl: (value: string) => string
    _replaceJSUrl: (value: string) => string
} = {
    _replaceFontCssUrls: (value: string | null): string | null => {
        return (
            value?.replace(
                /url\("(https:\/\/\S*(?:.eot|.woff2|.ttf|.woff)\S*)"\)/gi,
                `url("${PROXY_URL}/proxy?url=$1")`
            ) || null
        )
    },

    _replaceFontUrl: (value: string): string => {
        return value.replace(/^(https:\/\/\S*(?:.eot|.woff2|.ttf|.woff)\S*)$/i, `${PROXY_URL}/proxy?url=$1`)
    },

    _replaceJSUrl: (value: string): string => {
        return value.replace(/^(https:\/\/\S*(?:.js)\S*)$/i, `${PROXY_URL}/proxy?url=$1`)
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

export const COMMON_REPLAYER_CONFIG: Partial<playerConfig> = {
    triggerFocus: false,
    insertStyleRules: [
        `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
    ],
}
