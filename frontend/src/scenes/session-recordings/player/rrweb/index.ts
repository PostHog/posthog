import { ReplayPlugin } from 'rrweb/typings/types'
import { Replayer } from 'rrweb'
import { eventWithTime } from '@rrweb/types'

const PROXY_URL = 'https://replay-proxy.posthog.com' as const

export const CorsPlugin: ReplayPlugin & { _replaceFontURLs: (value: string) => string } = {
    _replaceFontURLs: (value: string): string => {
        const regex = /url\("https:\/\/\S*(.eot|.woff2|.ttf|.woff)\S*"\)/gm
        let matches
        const fontUrls: { original: string; replacement: string }[] = []

        while ((matches = regex.exec(value)) !== null) {
            // This is necessary to avoid infinite loops with zero-width matches
            if (matches.index === regex.lastIndex) {
                regex.lastIndex++
            }

            if (matches) {
                console.log(value)
            }

            matches.forEach((match, groupIndex) => {
                if (groupIndex === 0) {
                    // Trim the start and end
                    // example: url("https://app.posthog.com/fonts/my-font.woff2")
                    // gets trimmed to https://app.posthog.com/fonts/my-font.woff2
                    const url = match.slice(5, match.length - 2)

                    fontUrls.push({
                        original: url,
                        replacement: url.replace(url, `${PROXY_URL}?url=${url}`),
                    })
                }
            })
        }

        // Replace all references to the old URL to our proxy URL in the stylesheet.
        fontUrls.forEach((urlPair) => {
            value = (value as string).replace(urlPair.original, urlPair.replacement)
        })

        return value
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
