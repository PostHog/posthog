import Heading from '@tiptap/extension-heading'
import { Node as PMNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Editor, ReactRenderer } from '@tiptap/react'

import { IconEye, IconTriangleDownFilled, IconTriangleRightFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { humanList, identifierToHuman, pluralize } from 'lib/utils'

import { NotebookNodeType } from '../types'

/** h1-h3 are collapsible */
const MAX_COLLAPSIBLE_H_LEVEL = 3

// This is how the collapsed/expanded state is persisted - via the `collapsed` attribute on the node
export const CollapsibleHeading = Heading.extend({
    addAttributes() {
        return {
            // @ts-expect-error For some reason TypeScript doesn't like it, but this inheriting is necessary
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
    const topNodes: {
        node: any
        pos: number
        isHeading: boolean
        level?: number
        collapsed?: boolean
    }[] = []

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
                        const transaction = editor.state.tr.setNodeMarkup(headingStart, undefined, {
                            ...node.attrs,
                            collapsed: !node.attrs.collapsed,
                        })
                        editor.view.dispatch(transaction)
                    },
                },
            })
            decorations.push(Decoration.widget(headingStart + 1, renderer.element, { side: -1 }))
        }
    }

    // Hierarchy-aware hiding and content analysis
    let activeCollapse: [level: number, headingPos: number] | null = null
    let hiddenNodes: any[] = []
    for (const info of topNodes) {
        if (info.isHeading) {
            if (activeCollapse) {
                if ((info.level ?? Infinity) <= activeCollapse[0]) {
                    // Collapsed section starting
                    if (hiddenNodes.length > 0 && activeCollapse[1] !== null) {
                        decorations.push(createCollapsedContentDecoration(editor, doc, activeCollapse[1], hiddenNodes))
                    }
                    activeCollapse = null
                    hiddenNodes = []
                } else {
                    // Nested heading inside collapsed region – hide it
                    decorations.push(
                        Decoration.node(info.pos, info.pos + info.node.nodeSize, { style: 'display: none' })
                    )
                    continue
                }
            }
            if (info.collapsed) {
                activeCollapse = [info.level ?? Infinity, info.pos]
                hiddenNodes = []
                continue
            }
        } else if (activeCollapse) {
            // Hide this node nested in a collapsed region
            hiddenNodes.push(info.node)
            decorations.push(Decoration.node(info.pos, info.pos + info.node.nodeSize, { style: 'display: none' }))
        }
    }

    // If at end of file we're still in a collapsed region - emit its summary here
    if (activeCollapse !== null && hiddenNodes.length > 0) {
        decorations.push(createCollapsedContentDecoration(editor, doc, activeCollapse[1], hiddenNodes))
    }

    return DecorationSet.create(doc as any, decorations)
}

function HeadingToggle({ collapsed, onClick }: { collapsed: boolean; onClick?: () => void }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="xxsmall"
            tooltip={collapsed ? 'Click to expand' : 'Click to collapse'}
            onClick={onClick}
            icon={collapsed ? <IconTriangleRightFilled /> : <IconTriangleDownFilled />}
        />
    )
}
const createCollapsedContentDecoration = (
    editor: Editor,
    doc: PMNode,
    headingPos: number,
    nodes: any[]
): Decoration => {
    const summaryRenderer = new ReactRenderer(CollapsedContentSummary, {
        editor,
        props: {
            summary: summarizeCollapsedContent(nodes),
            onClick: () => {
                const node = editor.state.doc.nodeAt(headingPos)
                if (!node) {
                    console.error('No node found at headingPos', headingPos)
                    return
                }
                const tr = editor.state.tr.setNodeMarkup(headingPos, undefined, { ...node.attrs, collapsed: false })
                editor.view.dispatch(tr)
            },
        },
    })
    const headingNode = doc.nodeAt(headingPos)! // Assuming it exists, because - well - it's simpler
    return Decoration.widget(headingPos + headingNode.nodeSize, summaryRenderer.element, { side: 1 })
}

function CollapsedContentSummary({ summary, onClick }: { summary: string; onClick: () => void }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="xxsmall"
            onClick={onClick}
            icon={<IconEye />}
            className="italic -ml-1 opacity-80"
        >
            Expand for {summary}
        </LemonButton>
    )
}

function summarizeCollapsedContent(nodes: any[]): string {
    const counts: Partial<Record<NotebookNodeType, number>> = {}
    for (const node of nodes) {
        const nodeTypeName = node.type.name
        if (Object.values(NotebookNodeType).includes(nodeTypeName as NotebookNodeType)) {
            if (!counts[nodeTypeName as NotebookNodeType]) {
                counts[nodeTypeName as NotebookNodeType] = 0
            }
            counts[nodeTypeName as NotebookNodeType]! += 1
        }
    }
    return (
        humanList(
            Object.entries(counts).map(([nodeTypeName, count]) =>
                // The "Ph " comes form the notebook node identifiers starting with "ph-"
                pluralize(count, identifierToHuman(nodeTypeName, 'sentence').replace('Ph ', ''))
            )
        ) || 'collapsed content'
    )
}
