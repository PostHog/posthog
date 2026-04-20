// The `@react-email/editor` package ships its types under an `exports` subpath
// map, which requires `moduleResolution: "node16" | "nodenext" | "bundler"`.
// Our TS config uses classic `node` resolution, so TS can't discover these
// subpath modules automatically. We declare minimal shapes for the pieces we
// consume; the full typings ship with the package for IDE autocomplete via
// package.json `exports`.
declare module '@react-email/editor' {
    import type { Editor, Extensions, JSONContent } from '@tiptap/core'
    import type { ForwardRefExoticComponent, ReactNode, RefAttributes } from 'react'

    export interface EmailEditorRef {
        getEmail: () => Promise<{ html: string; text: string }>
        getEmailHTML: () => Promise<string>
        getEmailText: () => Promise<string>
        getJSON: () => JSONContent
        editor: Editor | null
    }

    export interface EmailEditorProps {
        content?: unknown
        onUpdate?: (ref: EmailEditorRef) => void
        onReady?: (ref: EmailEditorRef) => void
        theme?: unknown
        editable?: boolean
        placeholder?: string
        bubbleMenu?: {
            hideWhenActiveNodes?: string[]
            hideWhenActiveMarks?: string[]
        }
        extensions?: Extensions
        onUploadImage?: (file: File) => Promise<{ url: string }>
        className?: string
        children?: ReactNode
    }

    export const EmailEditor: ForwardRefExoticComponent<EmailEditorProps & RefAttributes<EmailEditorRef>>
}

declare module '@react-email/editor/extensions' {
    import type { Extension, Node } from '@tiptap/core'
    export const StarterKit: Extension
    export const Body: Node
    export const Section: Node
    export const Container: Node
    export const Button: Node
    export const Link: Node
    export const Heading: Node
    export const Paragraph: Node
    export const Text: Node
    // Other exports exist at runtime — omitted for brevity; consumers can cast.
    const _extras: Record<string, unknown>
    export default _extras
}

declare module '@react-email/editor/plugins' {
    import type { Extension } from '@tiptap/core'
    export const EmailTheming: Extension
    const _extras: Record<string, unknown>
    export default _extras
}

declare module '@react-email/editor/ui' {
    import type { Editor } from '@tiptap/core'
    import type { FC, ReactNode } from 'react'

    export interface SlashCommandItem {
        id: string
        title: string
        description?: string
        command: (props: { editor: Editor }) => void
    }

    export interface SlashCommandRootProps {
        items?: SlashCommandItem[]
        filterItems?: (items: SlashCommandItem[], query: string, editor: Editor) => SlashCommandItem[]
        char?: string
        allow?: (props: { editor: Editor }) => boolean
        children?: ReactNode
    }

    export const SlashCommand: FC<SlashCommandRootProps>
    export const SlashCommandRoot: FC<SlashCommandRootProps>
    export const defaultSlashCommands: SlashCommandItem[]
    const _extras: Record<string, unknown>
    export default _extras
}

declare module '@react-email/editor/themes/default.css'
declare module '@react-email/editor/styles/slash-command.css'
declare module '@react-email/editor/styles/bubble-menu.css'
declare module '@react-email/editor/styles/inspector.css'
