/**
 * Ambient type declarations for @react-email/editor and its CSS style subpaths.
 *
 * The package exposes its types via the `exports` field (Node16/NodeNext
 * resolution). We compile with classic `moduleResolution: "node"`, so TS
 * cannot find the declaration files directly. The runtime resolution still
 * works because Parcel/webpack respect `exports`. These declarations mirror
 * the public surface in `node_modules/@react-email/editor/dist/index.d.cts`.
 */

declare module '@react-email/editor' {
    import type { Content, Editor, Extensions, JSONContent } from '@tiptap/core'
    import type { ForwardRefExoticComponent, ReactNode, RefAttributes } from 'react'

    export interface EmailEditorRef {
        getEmail: () => Promise<{ html: string; text: string }>
        getEmailHTML: () => Promise<string>
        getEmailText: () => Promise<string>
        getJSON: () => JSONContent
        editor: Editor | null
    }

    export type EditorTheme = 'basic' | 'minimal'
    export interface EditorThemeConfig {
        extends?: EditorTheme
        styles: Record<string, React.CSSProperties & { align?: 'center' | 'left' | 'right' }>
    }
    export type EditorThemeInput = EditorTheme | EditorThemeConfig

    export interface EmailEditorProps {
        content?: Content
        onUpdate?: (ref: EmailEditorRef) => void
        onReady?: (ref: EmailEditorRef) => void
        theme?: EditorThemeInput
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

declare module '@react-email/editor/themes/default.css'
declare module '@react-email/editor/styles/bubble-menu.css'
declare module '@react-email/editor/styles/link-bubble-menu.css'
declare module '@react-email/editor/styles/button-bubble-menu.css'
declare module '@react-email/editor/styles/image-bubble-menu.css'
declare module '@react-email/editor/styles/slash-command.css'
declare module '@react-email/editor/styles/inspector.css'
