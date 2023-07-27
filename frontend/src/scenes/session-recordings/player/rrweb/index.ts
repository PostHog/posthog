import { ReplayPlugin } from 'rrweb/typings/types'
import { Replayer } from 'rrweb'
import { eventWithTime } from '@rrweb/types'

const PROXY_URL = 'https://replay-proxy.posthog.com' as const

export const CorsPlugin: ReplayPlugin & { _replaceFontURLs: (value: string) => string } = {
    _replaceFontURLs: (value: string): string => {
        return value.replace(/url\("(https:\/\/\S*(?:.eot|.woff2|.ttf|.woff)\S*)"\)/gi, `url("${PROXY_URL}?url=$1")`)
    },

    onBuild: (node) => {
        if (node.nodeName === 'STYLE') {
            const styleElement = node as HTMLStyleElement
            styleElement.innerText = CorsPlugin._replaceFontURLs(styleElement.innerText)
        }
    },
}

export const createReplayer = (events: eventWithTime[], root: Element): Replayer => {
    return new Replayer(events, {
        root,
        triggerFocus: false,
        insertStyleRules: [
            `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
        ],
        plugins: [CorsPlugin],
    })
}
