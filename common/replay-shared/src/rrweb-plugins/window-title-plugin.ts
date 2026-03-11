import { ReplayPlugin } from '@posthog/rrweb'
import { EventType, IncrementalSource, eventWithTime } from '@posthog/rrweb-types'

type Node = {
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
