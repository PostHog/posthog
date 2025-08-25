import Heading from '@tiptap/extension-heading'
import { Node as PMNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Editor, ReactRenderer } from '@tiptap/react'

import { IconTriangleDownFilled, IconTriangleUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

/** h1-h3 are collapsible */
const MAX_COLLAPSIBLE_H_LEVEL = 3

function HeadingToggle({ collapsed, onClick }: { collapsed: boolean; onClick: () => void }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="xxsmall"
            tooltip={collapsed ? 'Click to expand' : 'Click to collapse'}
            aria-expanded={!collapsed}
            onClick={onClick}
            icon={collapsed ? <IconTriangleUpFilled /> : <IconTriangleDownFilled />}
        />
    )
}

// This is how the collapsed/expanded state is persisted - via the `collapsed` attribute on the node
export const CollapsibleHeading = Heading.extend({
    addAttributes() {
        return {
            ...this.parent?.(),
            collapsed: {
                default: false,
                parseHTML: (element: HTMLElement) => element.getAttribute('data-collapsed') === 'true',
                renderHTML: (attributes: { collapsed?: boolean; level: number | undefined }) =>
                    (attributes.level ?? Infinity) <= MAX_COLLAPSIBLE_H_LEVEL
                        ? {
                              'data-collapsed': attributes.collapsed ? 'true' : 'false',
                          }
                        : {},
            },
        }
    },

    addProseMirrorPlugins() {
        const pluginKey = new PluginKey('collapsibleHeading')
        return [
            new Plugin({
                key: pluginKey,
                state: {
                    init: (_, { doc }) => createDecorations(doc, this.editor),
                    apply: (tr, old) => {
                        if (tr.docChanged || tr.selectionSet || (tr as any).getMeta('forceDecorations')) {
                            return createDecorations(tr.doc as PMNode, this.editor)
                        }
                        return old
                    },
                },
                props: {
                    decorations: (state) => pluginKey.getState(state),
                },
            }),
        ]
    },
})

function createDecorations(doc: PMNode, editor: Editor): DecorationSet {
    const decorations: Decoration[] = []

    type TopNodeInfo = {
        node: any
        pos: number
        isHeading: boolean
        level?: number
        collapsed?: boolean
    }

    const topNodes: TopNodeInfo[] = []
    doc.descendants((node, nodePos, parent) => {
        if (parent === doc) {
            topNodes.push({
                node,
                pos: nodePos,
                isHeading: node.type.name === 'heading',
                level: node.type.name === 'heading' ? node.attrs.level : undefined,
                collapsed: node.type.name === 'heading' ? !!node.attrs.collapsed : undefined,
            })
        }
    })

    // Caret button per heading via ReactRenderer
    for (const info of topNodes) {
        if (info.isHeading) {
            const isLevelCollapsible = info.level && info.level <= MAX_COLLAPSIBLE_H_LEVEL
            if (!isLevelCollapsible) {
                continue
            }
            const headingStart = info.pos
            const renderer = new ReactRenderer(HeadingToggle, {
                editor,
                props: {
                    collapsed: !!info.collapsed,
                    onClick: () => {
                        const node = editor.state.doc.nodeAt(headingStart)
                        if (!node) {
                            return
                        }
                        const tr = editor.state.tr.setNodeMarkup(headingStart, undefined, {
                            ...node.attrs,
                            collapsed: !node.attrs.collapsed,
                        })
                        tr.setMeta('forceDecorations', true)
                        editor.view.dispatch(tr)
                    },
                },
            })
            decorations.push(Decoration.widget(headingStart + 1, renderer.element, { side: -1 }))
        }
    }

    // Hierarchy-aware hiding
    let activeCollapsedLevel: number | null = null
    for (const info of topNodes) {
        if (info.isHeading) {
            if (activeCollapsedLevel !== null) {
                const nodeHLevel = info.level ?? Infinity
                if (nodeHLevel <= activeCollapsedLevel) {
                    activeCollapsedLevel = null
                }
            }
            if (info.collapsed) {
                activeCollapsedLevel = info.level ?? null
                continue
            }
        }

        if (activeCollapsedLevel !== null) {
            decorations.push(
                Decoration.node(info.pos, info.pos + info.node.nodeSize, {
                    'data-collapsed-by': String(activeCollapsedLevel),
                })
            )
        }
    }

    return DecorationSet.create(doc as any, decorations)
}
