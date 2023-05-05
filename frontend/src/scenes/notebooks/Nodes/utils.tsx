import { NodeViewProps } from '@tiptap/core'

export function useJsonNodeState(props: NodeViewProps, key: string): [any, (value: any) => void] {
    let value = props.node.attrs[key]
    try {
        value = typeof value === 'string' ? JSON.parse(value) : value
    } catch (e) {
        console.error("Couldn't parse query", e)
    }

    const setValue = (value: any): void => {
        props.updateAttributes({
            [key]: JSON.stringify(value),
        })
    }

    return [value, setValue]
}
