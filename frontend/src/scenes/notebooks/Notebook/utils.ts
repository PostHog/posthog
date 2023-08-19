// Helpers for Kea issue with double importing
import {
    JSONContent as TTJSONContent,
    Editor as TTEditor,
    ChainedCommands as EditorCommands,
    FocusPosition as EditorFocusPosition,
    Range as EditorRange,
    getText,
} from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'
import { NodeViewProps } from '@tiptap/react'
import { NotebookNodeType, NotebookTarget } from '~/types'
import { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { urls } from 'scenes/urls'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { BuiltLogic } from 'kea'
import { router } from 'kea-router'

/* eslint-disable @typescript-eslint/no-empty-interface */
export interface Node extends PMNode {}
export interface JSONContent extends TTJSONContent {}
/* eslint-enable @typescript-eslint/no-empty-interface */
// export type FocusPosition = number | boolean | 'start' | 'end' | 'all' | null

export {
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    FocusPosition as EditorFocusPosition,
} from '@tiptap/core'

export type NotebookNodeAttributes = Record<string, any>
type NotebookNode<T extends NotebookNodeAttributes> = Omit<PMNode, 'attrs'> & {
    attrs: T & {
        nodeId?: string
        height?: string | number
    }
}

export type NotebookNodeViewProps<T extends NotebookNodeAttributes> = Omit<NodeViewProps, 'node'> & {
    node: NotebookNode<T>
}

export interface NotebookEditor {
    getJSON: () => JSONContent
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    focus: (position: EditorFocusPosition) => void
    destroy: () => void
    isEmpty: () => boolean
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent) => void
    insertContentAfterNode: (position: number, content: JSONContent) => void
    findNode: (position: number) => Node | null
    findNodePositionByAttrs: (attrs: Record<string, any>) => any
    nextNode: (position: number) => { node: Node; position: number } | null
    hasChildOfType: (node: Node, type: string) => boolean
}

// Loosely based on https://github.com/ueberdosis/tiptap/blob/develop/packages/extension-floating-menu/src/floating-menu-plugin.ts#LL38C3-L55C4
export const isCurrentNodeEmpty = (editor: TTEditor): boolean => {
    const selection = editor.state.selection
    const { $anchor, empty } = selection
    const isEmptyTextBlock =
        $anchor.parent.isTextblock && !$anchor.parent.type.spec.code && !textContent($anchor.parent)

    if (empty && isEmptyTextBlock) {
        return true
    }

    return false
}

const textContent = (node: any): string => {
    return getText(node, {
        blockSeparator: ' ',
        textSerializers: {
            [NotebookNodeType.ReplayTimestamp]: ({ node }) => `${node.attrs.playbackTime || '00:00'}: `,
        },
    })
}

export function defaultNotebookContent(title?: string, content?: JSONContent[]): JSONContent {
    const initialContent = [
        {
            type: 'heading',
            attrs: { level: 1 },
            content: [{ type: 'text', text: title }],
        },
    ] as JSONContent[]

    if (content) {
        initialContent.push(...content)
    }

    return { type: 'doc', content: initialContent }
}

export const openNotebook = async (
    notebookId: string,
    target: NotebookTarget = NotebookTarget.Auto,
    focus: EditorFocusPosition = null,
    // operations to run against the notebook once it has opened and the editor is ready
    onOpen: (logic: BuiltLogic<notebookLogicType>) => void = () => {}
): Promise<void> => {
    const popoverLogic = notebookPopoverLogic.findMounted()

    if (NotebookTarget.Popover === target) {
        popoverLogic?.actions.setVisibility('visible')
    }

    if (popoverLogic?.values.visibility === 'visible') {
        popoverLogic?.actions.selectNotebook(notebookId)
    } else {
        router.actions.push(urls.notebookEdit(notebookId))
    }

    popoverLogic?.actions.setInitialAutofocus(focus)

    const theNotebookLogic = notebookLogic({ shortId: notebookId })
    const unmount = theNotebookLogic.mount()

    try {
        onOpen(theNotebookLogic)
    } finally {
        unmount()
    }
}
