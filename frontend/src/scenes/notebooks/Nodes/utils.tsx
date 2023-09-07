import { ExtendedRegExpMatchArray, NodeViewProps, PasteRule } from '@tiptap/core'
import posthog from 'posthog-js'
import { NodeType } from '@tiptap/pm/model'
import { Editor as TTEditor } from '@tiptap/core'
import { CustomNotebookNodeAttributes, NotebookNodeAttributes } from '../Notebook/utils'
import { useCallback, useMemo } from 'react'
import { jsonParse, uuid } from 'lib/utils'

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

    const attributes = useMemo(() => {
        // Here we parse all properties that could be objects.

        const parsedAttrs = Object.keys(props.node.attrs).reduce(
            (acc, x) => ({
                ...acc,
                [x]: jsonParse(props.node.attrs[x], props.node.attrs[x]),
            }),
            {}
        )

        return { ...parsedAttrs, nodeId } as NotebookNodeAttributes<T>
    }, [props.node.attrs, nodeId])

    const updateAttributes = useCallback(
        (attrs: Partial<NotebookNodeAttributes<T>>): void => {
            // We call the update whilst json stringifying
            const stringifiedAttrs = Object.keys(attrs).reduce(
                (acc, x) => ({
                    ...acc,
                    [x]: JSON.stringify(attrs[x]),
                }),
                {}
            )

            props.updateAttributes(stringifiedAttrs)
        },
        [props.updateAttributes]
    )

    return [attributes, updateAttributes]
}
