import { ExtendedRegExpMatchArray, NodeViewProps, PasteRule, nodePasteRule } from '@tiptap/core'
import posthog from 'posthog-js'
import { NodeType } from '@tiptap/pm/model'

export function useJsonNodeState<T>(props: NodeViewProps, key: string): [T, (value: T) => void] {
    let value = props.node.attrs[key]
    try {
        value = typeof value === 'string' ? JSON.parse(value) : value
    } catch (e) {
        console.error("Couldn't parse query", e)
        value = {}
    }

    const setValue = (value: any): void => {
        props.updateAttributes({
            [key]: JSON.stringify(value),
        })
    }

    return [value, setValue]
}

export function createUrlRegex(path: string, origin?: string): RegExp {
    origin = (origin || window.location.origin).replace('.', '\\.')

    return new RegExp(origin + path, 'ig')
}

export function reportNotebookNodeCreation(nodeType: string): void {
    posthog.capture('notebook node created', { type: nodeType })
}

export function posthogNodePasteRule(options: {
    find: string
    type: NodeType
    getAttributes: (match: ExtendedRegExpMatchArray) => Record<string, any> | null | undefined
}): PasteRule {
    return nodePasteRule({
        find: createUrlRegex(options.find),
        type: options.type,
        getAttributes: (match) => {
            const attrs = options.getAttributes(match)
            posthog.capture('notebook node pasted', { node_type: options.type.name })
            return attrs
        },
    })
}

export function externalLinkPasteRule(options: {
    find: string
    type: NodeType
    getAttributes: (match: ExtendedRegExpMatchArray) => Record<string, any> | null | undefined
}): PasteRule {
    return nodePasteRule({
        find: createUrlRegex(options.find, '(https?|mailto)://'),
        type: options.type,
        getAttributes: (match) => {
            const attrs = options.getAttributes(match)
            return attrs
        },
    })
}
