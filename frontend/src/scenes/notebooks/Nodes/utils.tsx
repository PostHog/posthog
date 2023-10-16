import { ExtendedRegExpMatchArray, NodeViewProps, PasteRule } from '@tiptap/core'
import posthog from 'posthog-js'
import { NodeType } from '@tiptap/pm/model'
import { Editor as TTEditor } from '@tiptap/core'
import { CustomNotebookNodeAttributes, NotebookNodeAttributes } from '../Notebook/utils'
import { useCallback, useMemo, useRef } from 'react'
import { tryJsonParse, uuid } from 'lib/utils'

export function createUrlRegex(path: string | RegExp, origin?: string): RegExp {
    origin = (origin || window.location.origin).replace('.', '\\.')
    return new RegExp(origin + path, 'ig')
}

export function reportNotebookNodeCreation(nodeType: string): void {
    posthog.capture('notebook node created', { type: nodeType })
}

export function posthogNodePasteRule(options: {
    find: string
    type: NodeType
    editor: TTEditor
    getAttributes: (
        match: ExtendedRegExpMatchArray
    ) => Promise<Record<string, any> | null | undefined> | Record<string, any> | null | undefined
}): PasteRule {
    return new PasteRule({
        find: createUrlRegex(options.find),
        handler: ({ match, chain, range }) => {
            if (match.input) {
                chain().deleteRange(range).run()
                Promise.resolve(options.getAttributes(match)).then((attributes) => {
                    if (attributes) {
                        options.editor.commands.insertContent({
                            type: options.type.name,
                            attrs: attributes,
                        })
                    }
                })
            }
        },
    })
}

export function linkPasteRule(): PasteRule {
    return new PasteRule({
        find: createUrlRegex(
            `(?!${window.location.host})([a-zA-Z0-9-._~:/?#\\[\\]!@$&'()*,;=]*)`,
            '^(https?|mailto)://'
        ),
        handler: ({ match, chain, range }) => {
            if (match.input) {
                const url = new URL(match[0])
                const href = url.origin === window.location.origin ? url.pathname : url.toString()
                chain()
                    .deleteRange(range)
                    .insertContent([
                        {
                            type: 'text',
                            marks: [{ type: 'link', attrs: { href } }],
                            text: href,
                        },
                        { type: 'text', text: ' ' },
                    ])
                    .run()
            }
        },
    })
}

export function selectFile(options: { contentType: string; multiple: boolean }): Promise<File[]> {
    return new Promise((resolve, reject) => {
        const input = document.createElement('input')
        input.type = 'file'
        input.multiple = options.multiple
        input.accept = options.contentType

        input.onchange = () => {
            if (!input.files) {
                return resolve([])
            }
            const files = Array.from(input.files)
            resolve(files)
        }

        input.oncancel = () => {
            resolve([])
        }
        input.onerror = () => {
            reject(new Error('Error selecting file'))
        }

        input.click()
    })
}

export function useSyncedAttributes<T extends CustomNotebookNodeAttributes>(
    props: NodeViewProps
): [NotebookNodeAttributes<T>, (attrs: Partial<NotebookNodeAttributes<T>>) => void] {
    const nodeId = useMemo(() => props.node.attrs.nodeId ?? uuid(), [props.node.attrs.nodeId])
    const previousNodeAttrs = useRef<NodeViewProps['node']['attrs']>()
    const parsedAttrs = useRef<NotebookNodeAttributes<T>>({} as NotebookNodeAttributes<T>)

    if (previousNodeAttrs.current !== props.node.attrs) {
        const newParsedAttrs = {}

        Object.keys(props.node.attrs).forEach((key) => {
            if (previousNodeAttrs.current?.[key] !== props.node.attrs[key]) {
                // If changed, set it whilst trying to parse
                newParsedAttrs[key] = tryJsonParse(props.node.attrs[key], props.node.attrs[key])
            } else if (parsedAttrs.current) {
                // Otherwise use the old value to preserve object equality
                newParsedAttrs[key] = parsedAttrs.current[key]
            }
        })

        parsedAttrs.current = newParsedAttrs as NotebookNodeAttributes<T>
        parsedAttrs.current.nodeId = nodeId
    }

    previousNodeAttrs.current = props.node.attrs

    const updateAttributes = useCallback(
        (attrs: Partial<NotebookNodeAttributes<T>>): void => {
            // We call the update whilst json stringifying
            const stringifiedAttrs = Object.keys(attrs).reduce(
                (acc, x) => ({
                    ...acc,
                    [x]: attrs[x] && typeof attrs[x] === 'object' ? JSON.stringify(attrs[x]) : attrs[x],
                }),
                {}
            )

            const hasChanges = Object.keys(stringifiedAttrs).some(
                (key) => previousNodeAttrs.current?.[key] !== stringifiedAttrs[key]
            )

            if (!hasChanges) {
                return
            }

            // NOTE: queueMicrotask protects us from TipTap's flushSync calls, ensuring we never modify the state whilst the flush is happening
            queueMicrotask(() => props.updateAttributes(stringifiedAttrs))
        },
        [props.updateAttributes]
    )

    return [parsedAttrs.current, updateAttributes]
}
