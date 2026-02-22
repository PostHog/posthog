import { createElement } from 'react'

interface HastText {
    type: 'text'
    value: string
}

interface HastElement {
    type: 'element'
    tagName: string
    properties?: { className?: string[] }
    children?: HastNode[]
}

interface HastRoot {
    type: 'root'
    children?: HastNode[]
}

export type HastNode = HastText | HastElement | HastRoot

export function hastToReact(node: HastNode, key?: number): React.ReactNode {
    if (node.type === 'text') {
        return node.value
    }
    if (node.type === 'element') {
        return createElement(
            node.tagName,
            { key, className: node.properties?.className?.join(' ') || undefined },
            node.children?.map((child, i) => hastToReact(child, i))
        )
    }
    if (node.type === 'root') {
        return node.children?.map((child, i) => hastToReact(child, i))
    }
    return null
}
