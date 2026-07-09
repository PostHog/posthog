import { Editor, JSONContent } from '@tiptap/core'
import { EditorContent, Extensions } from '@tiptap/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import 'lib/components/MarkdownEditor/shared/RichMarkdownEditor.scss'
import { MarkdownEditorCharacterCountFooter } from 'lib/components/MarkdownEditor/shared/MarkdownEditorCharacterCountFooter'
import { getTiptapEditorDom } from 'lib/components/MarkdownEditor/shared/tiptapEditorDom'
import { useMarkdownEditorControlledAndFormEffects } from 'lib/components/MarkdownEditor/shared/useMarkdownEditorControlledAndFormEffects'
import { useMarkdownEditorImageUpload } from 'lib/components/MarkdownEditor/shared/useMarkdownEditorImageUpload'
import { useRichContentEditor } from 'lib/components/RichContentEditor'

import {
    createInlineMarkdownSlashCommandsExtension,
    DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS,
    INLINE_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY,
    type InlineMarkdownSlashCommandItem,
    type InlineMarkdownSlashImageHostRef,
    type InlineMarkdownSlashLinkHostRef,
} from './inlineMarkdownSlashCommands'
import { RichMarkdownEditorBubbleMenu } from './RichMarkdownEditorBubbleMenu'

export type InlineRichMarkdownEditorProps = {
    value?: string
    onChange?: (value: string) => void
    minRows?: number
    maxRows?: number
    maxLength?: number
    dataAttr?: string
    extensions: Extensions
    markdownToDoc: (markdown: string | null | undefined) => JSONContent
    docToMarkdown: (doc: JSONContent) => string
    autoFocus?: boolean
    className?: string
    /** Toggle individual features on/off. Any key omitted keeps its default. */
    controls?: {
        /** Bubble menu + slash-command image upload (requires object storage). Default true. */
        imageUpload?: boolean
        /** Bubble menu emoji picker. Default true. */
        emoji?: boolean
        /** Append `/` slash command menu (grouped sections, filter as you type). Default false. */
        slashCommands?: boolean
        /** Character count footer. Default true. */
        characterCount?: boolean
    }
    /** Custom slash items when `controls.slashCommands` is on (defaults match bubble / rich formatting toolbar) */
    slashCommandItems?: InlineMarkdownSlashCommandItem[]
}

/**
 * BubbleMenu registers ProseMirror plugins that touch editor.view immediately. Tiptap only sets
 * editorView and emits `create` after mount (see Editor.mount). Defer the bubble until then so
 * Storybook / Strict Mode don't crash.
 */
function useBubbleMenuSafeToMount(editor: Editor | null): boolean {
    const [ready, setReady] = useState(false)

    useEffect(() => {
        if (!editor) {
            setReady(false)
            return
        }

        const markReady = (): void => {
            setReady(true)
        }

        if (editor.isInitialized) {
            markReady()
        } else {
            editor.on('create', markReady)
        }

        return () => {
            editor.off('create', markReady)
            setReady(false)
        }
    }, [editor])

    return ready
}

/**
 * Markdown editor with a Notion-style bubble menu on text selection (no fixed formatting toolbar).
 * For tabs + toolbar + preview, use `RichMarkdownEditor` (`MarkdownEditor/rich/`).
 */
export function InlineRichMarkdownEditor({
    value,
    onChange,
    minRows = 8,
    maxRows = 20,
    maxLength = 4000,
    dataAttr = 'inline-rich-markdown-editor-area',
    extensions,
    markdownToDoc,
    docToMarkdown,
    autoFocus = false,
    className = '',
    controls,
    slashCommandItems,
}: InlineRichMarkdownEditorProps): JSX.Element {
    const showImageUpload = controls?.imageUpload ?? true
    const showEmoji = controls?.emoji ?? true
    const showSlashCommands = controls?.slashCommands ?? false
    const showCharacterCount = controls?.characterCount ?? true
    const [linkUrl, setLinkUrl] = useState('')
    const [showLinkPopover, setShowLinkPopover] = useState(false)
    const [linkPopoverReferenceElement, setLinkPopoverReferenceElement] = useState<HTMLElement | null>(null)
    const lastSyncedMarkdownRef = useRef(value || '')
    const dropRef = useRef<HTMLDivElement>(null)
    const slashImageFileInputRef = useRef<HTMLInputElement>(null)
    const slashImageHostRef = useRef<InlineMarkdownSlashImageHostRef | null>(null)
    const slashLinkHostRef = useRef<InlineMarkdownSlashLinkHostRef | null>(null)
    const setSlashImageFilesRef = useRef<(files: File[]) => void>(() => {})

    const clearLinkPopoverReference = useCallback(() => setLinkPopoverReferenceElement(null), [])

    const setShowLinkPopoverTracked = useCallback((visible: boolean): void => {
        setShowLinkPopover(visible)
        if (!visible) {
            setLinkPopoverReferenceElement(null)
        }
    }, [])

    const syncMarkdownFromEditor = useCallback(
        (nextMarkdown: string, options?: { force?: boolean }): void => {
            if (nextMarkdown === lastSyncedMarkdownRef.current) {
                return
            }

            lastSyncedMarkdownRef.current = nextMarkdown
            if (options?.force) {
                flushSync(() => onChange?.(nextMarkdown))
                return
            }

            onChange?.(nextMarkdown)
        },
        [onChange]
    )

    const resolvedExtensions = useMemo((): Extensions => {
        if (!showSlashCommands) {
            return extensions
        }
        return [
            ...extensions,
            createInlineMarkdownSlashCommandsExtension(
                INLINE_MARKDOWN_SLASH_COMMANDS_PLUGIN_KEY,
                slashCommandItems ?? DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS,
                { slashImageHostRef, slashLinkHostRef }
            ),
        ]
    }, [extensions, showSlashCommands, slashCommandItems])

    const editor = useRichContentEditor({
        extensions: resolvedExtensions,
        initialContent: markdownToDoc(value),
        onUpdate: (content) => syncMarkdownFromEditor(docToMarkdown(content)),
    })

    const { setFilesToUpload } = useMarkdownEditorImageUpload(editor)

    const bubbleMenuSafeToMount = useBubbleMenuSafeToMount(editor)

    useEffect(() => {
        if (!editor || !autoFocus || !getTiptapEditorDom(editor)) {
            return
        }
        // Match RichMarkdownEditor: defer focus so Safari does not race TipTap transactions.
        const id = window.setTimeout(() => {
            if (!editor.isDestroyed) {
                editor.commands.focus()
            }
        }, 0)
        return () => window.clearTimeout(id)
    }, [editor, autoFocus, editor?.isInitialized])

    useMarkdownEditorControlledAndFormEffects({
        editor,
        value,
        markdownToDoc,
        docToMarkdown,
        lastSyncedMarkdownRef,
        syncMarkdownFromEditor,
    })

    setSlashImageFilesRef.current = setFilesToUpload
    slashImageHostRef.current = {
        pick: () => {
            slashImageFileInputRef.current?.click()
        },
        showSlashImageUpload: showImageUpload,
    }
    slashLinkHostRef.current = {
        openLinkPopover: () => {
            if (!editor) {
                return
            }
            const previousUrl = editor.getAttributes('link').href || ''
            setLinkUrl(String(previousUrl ?? ''))
            setLinkPopoverReferenceElement(getTiptapEditorDom(editor) ?? null)
            setShowLinkPopover(true)
        },
    }

    const currentMarkdown = editor ? docToMarkdown(editor.getJSON()) : value || ''

    return (
        <div ref={dropRef} className={`RichMarkdownEditor border rounded overflow-hidden ${className}`.trim()}>
            {/*
              EditorContent must mount before BubbleMenu: Tiptap creates editor.view in EditorContent's
              componentDidMount; BubbleMenu reads view.dom on mount and crashes if this runs first.
            */}
            <EditorContent
                editor={editor}
                className="RichMarkdownEditor__content px-3 py-2 overflow-auto"
                style={{ minHeight: `${minRows * 1.5}em`, maxHeight: `${maxRows * 1.5}em` }}
                data-attr={dataAttr}
            />
            {bubbleMenuSafeToMount ? (
                <RichMarkdownEditorBubbleMenu
                    editor={editor}
                    linkUrl={linkUrl}
                    setLinkUrl={setLinkUrl}
                    showLinkPopover={showLinkPopover}
                    setShowLinkPopover={setShowLinkPopoverTracked}
                    linkPopoverReferenceElement={linkPopoverReferenceElement}
                    clearLinkPopoverReference={clearLinkPopoverReference}
                    alternativeDropTargetRef={dropRef}
                    showImageUpload={showImageUpload}
                    showEmoji={showEmoji}
                />
            ) : null}
            {showCharacterCount ? (
                <MarkdownEditorCharacterCountFooter currentLength={currentMarkdown.length} maxLength={maxLength} />
            ) : null}
            <input
                ref={slashImageFileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                aria-hidden
                tabIndex={-1}
                data-attr="inline-rich-markdown-slash-image-input"
                onChange={(e) => {
                    const { files } = e.target
                    if (files?.length) {
                        setSlashImageFilesRef.current(Array.from(files))
                    }
                    e.target.value = ''
                }}
            />
        </div>
    )
}
