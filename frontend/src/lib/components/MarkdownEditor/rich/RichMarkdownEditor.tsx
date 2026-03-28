import { JSONContent } from '@tiptap/core'
import { EditorContent, Extensions } from '@tiptap/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import 'lib/components/MarkdownEditor/shared/RichMarkdownEditor.scss'
import { MarkdownEditorCharacterCountFooter } from 'lib/components/MarkdownEditor/shared/MarkdownEditorCharacterCountFooter'
import {
    MarkdownEditorImageEmojiControls,
    MarkdownEditorMarkdownFormatHintGlyph,
} from 'lib/components/MarkdownEditor/shared/MarkdownEditorImageEmojiControls'
import { RichMarkdownEditorFormatControls } from 'lib/components/MarkdownEditor/shared/RichMarkdownEditorFormatControls'
import { getTiptapEditorDom } from 'lib/components/MarkdownEditor/shared/tiptapEditorDom'
import { useMarkdownEditorControlledAndFormEffects } from 'lib/components/MarkdownEditor/shared/useMarkdownEditorControlledAndFormEffects'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

export type RichMarkdownEditorProps = {
    value?: string
    onChange?: (value: string) => void
    minRows?: number
    maxRows?: number
    maxLength?: number
    dataAttr?: string
    extensions: Extensions
    markdownToDoc: (markdown: string | null | undefined) => JSONContent
    docToMarkdown: (doc: JSONContent) => string
    renderPreview?: (markdown: string) => JSX.Element
    /** When true, focuses the editor once the ProseMirror view is mounted (default false to avoid stealing focus). */
    autoFocus?: boolean
}

export function RichMarkdownEditor({
    value,
    onChange,
    minRows = 8,
    maxRows = 20,
    maxLength = 4000,
    dataAttr = 'rich-markdown-editor-area',
    extensions,
    markdownToDoc,
    docToMarkdown,
    renderPreview,
    autoFocus = false,
}: RichMarkdownEditorProps): JSX.Element {
    const [activeTab, setActiveTab] = useState<'write' | 'preview' | 'markdown'>('write')
    const [linkUrl, setLinkUrl] = useState('')
    const [showLinkPopover, setShowLinkPopover] = useState(false)
    const dropRef = useRef<HTMLDivElement>(null)
    const lastSyncedMarkdownRef = useRef(value || '')

    const syncMarkdownFromEditor = useCallback(
        (nextMarkdown: string, options?: { force?: boolean }): void => {
            // Centralize editor -> form sync from multiple triggers (onUpdate, tab switch, submit).
            // We dedupe identical markdown to avoid noisy onChange loops, and force a synchronous flush on submit
            // so non-typing updates (e.g. image resize attrs) are committed before form submission continues.
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

    const editor = useRichContentEditor({
        extensions,
        initialContent: markdownToDoc(value),
        onUpdate: (content) => syncMarkdownFromEditor(docToMarkdown(content)),
    })

    useEffect(() => {
        if (editor && autoFocus && getTiptapEditorDom(editor)) {
            editor.commands.focus()
        }
    }, [editor, autoFocus, editor?.isInitialized])

    useMarkdownEditorControlledAndFormEffects({
        editor,
        value,
        markdownToDoc,
        docToMarkdown,
        lastSyncedMarkdownRef,
        syncMarkdownFromEditor,
    })

    const currentMarkdown = editor ? docToMarkdown(editor.getJSON()) : value || ''

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={(key) => {
                const nextTab = key as 'write' | 'preview' | 'markdown'
                setActiveTab(nextTab)

                // Keep parent value in sync before showing preview/markdown tabs.
                if (editor && nextTab !== 'write') {
                    syncMarkdownFromEditor(docToMarkdown(editor.getJSON()))
                }
            }}
            tabs={[
                {
                    key: 'write',
                    label: 'Write',
                    content: (
                        <div ref={dropRef} className="RichMarkdownEditor border rounded overflow-hidden">
                            <div className="flex min-w-0 items-center gap-0.5 border-b p-1">
                                <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto whitespace-nowrap">
                                    <LemonButton
                                        size="small"
                                        icon={<IconArrowLeft />}
                                        onClick={() => editor?.chain().focus().undo().run()}
                                        disabledReason={
                                            editor?.can().chain().focus().undo().run() ? undefined : 'Nothing to undo'
                                        }
                                        tooltip="Undo"
                                    />
                                    <LemonButton
                                        size="small"
                                        icon={<IconArrowRight />}
                                        onClick={() => editor?.chain().focus().redo().run()}
                                        disabledReason={
                                            editor?.can().chain().focus().redo().run() ? undefined : 'Nothing to redo'
                                        }
                                        tooltip="Redo"
                                    />
                                    <LemonDivider vertical className="mx-1 self-stretch" />
                                    <RichMarkdownEditorFormatControls
                                        editor={editor}
                                        linkUrl={linkUrl}
                                        setLinkUrl={setLinkUrl}
                                        showLinkPopover={showLinkPopover}
                                        setShowLinkPopover={setShowLinkPopover}
                                    />
                                    <LemonDivider vertical className="mx-1 self-stretch" />
                                    <MarkdownEditorImageEmojiControls
                                        editor={editor}
                                        alternativeDropTargetRef={dropRef}
                                        emojiPopoverDataAttr="rich-markdown-editor-emoji-popover"
                                    />
                                </div>
                                <div className="flex shrink-0 items-center border-l border-primary pl-2">
                                    <MarkdownEditorMarkdownFormatHintGlyph />
                                </div>
                            </div>
                            <EditorContent
                                editor={editor}
                                className="RichMarkdownEditor__content px-3 py-2 overflow-auto"
                                style={{ minHeight: `${minRows * 1.5}em`, maxHeight: `${maxRows * 1.5}em` }}
                                data-attr={dataAttr}
                            />
                            <MarkdownEditorCharacterCountFooter
                                currentLength={currentMarkdown.length}
                                maxLength={maxLength}
                            />
                        </div>
                    ),
                },
                {
                    key: 'preview',
                    label: 'Preview',
                    content: currentMarkdown ? (
                        (renderPreview?.(currentMarkdown) ?? <LemonMarkdown>{currentMarkdown}</LemonMarkdown>)
                    ) : (
                        <i>Nothing to preview</i>
                    ),
                },
                {
                    key: 'markdown',
                    label: 'Markdown',
                    content: currentMarkdown ? (
                        <pre className="RichMarkdownEditor__rawPreview">{currentMarkdown}</pre>
                    ) : (
                        <i>Nothing to preview</i>
                    ),
                },
            ]}
        />
    )
}
