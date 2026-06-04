import type { ReactNode } from 'react'

export type NotebookMode = 'view' | 'edit'

export type NotebookInlineMark =
    | { type: 'bold' }
    | { type: 'italic' }
    | { type: 'underline' }
    | { type: 'code' }
    | { type: 'link'; href: string }

export type NotebookTextInlineNode = {
    type: 'text'
    text: string
    marks?: NotebookInlineMark[]
}

export type NotebookHardBreakInlineNode = {
    type: 'hardBreak'
}

export type NotebookInlineNode = NotebookTextInlineNode | NotebookHardBreakInlineNode

export type NotebookPropValue =
    | string
    | number
    | boolean
    | null
    | NotebookPropValue[]
    | { [key: string]: NotebookPropValue }

export type NotebookComponentProps = Record<string, NotebookPropValue>

export type NotebookTextBlockNode = {
    id: string
    type: 'paragraph' | 'heading' | 'blockquote'
    level?: 1 | 2 | 3 | 4 | 5 | 6
    children: NotebookInlineNode[]
}

export type NotebookListItem = {
    children: NotebookInlineNode[]
    depth: number
    ordered?: boolean
}

export type NotebookListBlockNode = {
    id: string
    type: 'list'
    ordered: boolean
    items: NotebookListItem[]
}

export type NotebookCodeBlockNode = {
    id: string
    type: 'code'
    language?: string
    text: string
}

export type NotebookComponentBlockNode = {
    id: string
    type: 'component'
    tagName: string
    props: NotebookComponentProps
    raw?: string
    errors?: string[]
}

export type NotebookBlockNode =
    | NotebookTextBlockNode
    | NotebookListBlockNode
    | NotebookCodeBlockNode
    | NotebookComponentBlockNode

export type NotebookDocument = {
    type: 'doc'
    nodes: NotebookBlockNode[]
    errors: NotebookParseError[]
}

export type NotebookParseError = {
    message: string
    raw: string
    line: number
}

export type NotebookTextSelectionRange = {
    nodeId: string
    start: number
    end: number
}

export type NotebookComponentRenderProps = {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    updateProps: (props: Partial<NotebookComponentProps>) => void
}

export type NotebookComponentDefinition = {
    tagName: string
    label: string
    description?: string
    category: string
    aliases?: string[]
    icon?: ReactNode
    defaultProps?: NotebookComponentProps | (() => NotebookComponentProps)
    validateProps?: (props: NotebookComponentProps) => string[]
    ViewComponent: (props: NotebookComponentRenderProps) => JSX.Element
    EditComponent?: (props: NotebookComponentRenderProps) => JSX.Element
}

export type NotebookComponentRegistry = {
    components: Record<string, NotebookComponentDefinition>
}

export type NotebookReconcileChange =
    | { type: 'inserted'; nodeId: string; index: number }
    | { type: 'deleted'; nodeId: string; previousIndex: number }
    | { type: 'updated'; nodeId: string; index: number }
    | { type: 'moved'; nodeId: string; previousIndex: number; index: number }

export type NotebookCollaborationConflict = {
    nodeId: string
    reason: string
    localMarkdown: string
    remoteMarkdown: string
}
