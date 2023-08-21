import { ExtendedRegExpMatchArray, NodeViewProps, PasteRule } from '@tiptap/core'
import posthog from 'posthog-js'
import { NodeType } from '@tiptap/pm/model'
import { Editor as TTEditor } from '@tiptap/core'

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
                    if (!!attributes) {
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
