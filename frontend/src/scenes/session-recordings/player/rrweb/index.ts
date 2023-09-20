import { ReplayPlugin, playerConfig } from 'rrweb/typings/types'

const PROXY_URL = 'https://replay.ph-proxy.com' as const

export const CorsPlugin: ReplayPlugin & {
    _replaceFontCssUrls: (value: string) => string
    _replaceFontUrl: (value: string) => string
} = {
    _replaceFontCssUrls: (value: string): string => {
        return value.replace(
            /url\("(https:\/\/\S*(?:.eot|.woff2|.ttf|.woff)\S*)"\)/gi,
            `url("${PROXY_URL}/proxy?url=$1")`
        )
    },

    _replaceFontUrl: (value: string): string => {
        return value.replace(/^(https:\/\/\S*(?:.eot|.woff2|.ttf|.woff)\S*)$/i, `${PROXY_URL}/proxy?url=$1`)
    },

    onBuild: (node) => {
        if (node.nodeName === 'STYLE') {
            const styleElement = node as HTMLStyleElement
            styleElement.innerText = CorsPlugin._replaceFontCssUrls(styleElement.innerText)
        }

        if (node.nodeName === 'LINK') {
            const linkElement = node as HTMLLinkElement
            linkElement.href = CorsPlugin._replaceFontUrl(linkElement.href)
        }
    },
}

export const COMMON_REPLAYER_CONFIG: Partial<playerConfig> = {
    triggerFocus: false,
    insertStyleRules: [
        `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
    ],
}
