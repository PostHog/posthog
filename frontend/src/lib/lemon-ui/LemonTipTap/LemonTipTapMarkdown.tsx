import { useActions, useValues } from 'kea'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconMarkdown } from 'lib/lemon-ui/icons'
import { IconImage } from '@posthog/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'
import React, { useRef, useState, useCallback, useEffect } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import Typography from '@tiptap/extension-typography'
import Placeholder from '@tiptap/extension-placeholder'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea'

interface RichContentPreviewProps {
    richContent: any
}

function RichContentPreview({ richContent }: RichContentPreviewProps): JSX.Element {
    const previewEditor = useEditor(
        {
            extensions: [
                StarterKit.configure({}),
                Image.configure({
                    inline: true,
                    allowBase64: true,
                }),
                Typography,
            ],
            content: richContent,
            editable: false,
        },
        [richContent]
    )

    if (!previewEditor) {
        return <div>Loading preview...</div>
    }

    return (
        <div className="LemonTextArea--preview">
            <EditorContent editor={previewEditor} />
        </div>
    )
}

export interface LemonTipTapMarkdownProps extends Omit<LemonTextAreaProps, 'value' | 'onChange'> {
    /** Legacy markdown/text content for backward compatibility */
    value?: string
    /** Modern rich content in TipTap JSON format */
    richContent?: any
    /** Callback for legacy text changes */
    onChange?: (value: string) => void
    /** Callback for rich content changes */
    onRichContentChange?: (content: any) => void
}

export const LemonTipTapMarkdown = React.forwardRef<HTMLDivElement, LemonTipTapMarkdownProps>(
    function LemonTipTapMarkdown(
        { value, richContent, onChange, onRichContentChange, className, maxLength, ...editAreaProps },
        ref
    ): JSX.Element {
        const { objectStorageAvailable } = useValues(preflightLogic)
        const { emojiUsed } = useActions(emojiUsageLogic)

        const [isPreviewShown, setIsPreviewShown] = useState(false)
        const dropRef = useRef<HTMLDivElement>(null)
        const editorRef = useRef<HTMLDivElement>(null)
        const isUpdatingFromProp = useRef(false)

        const combinedRef = useCallback(
            (element: HTMLDivElement | null) => {
                // Store reference in our local ref
                ;(editorRef as React.MutableRefObject<HTMLDivElement | null>).current = element
                // Forward to the original ref
                if (typeof ref === 'function') {
                    ref(element)
                } else if (ref) {
                    ;(ref as React.MutableRefObject<HTMLDivElement | null>).current = element
                }
            },
            [ref]
        )

        const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
            onUpload: (url, fileName) => {
                if (editor) {
                    // Use TipTap's native image command - more idiomatic!
                    editor.commands.setImage({
                        src: url,
                        alt: fileName,
                        title: fileName,
                    })

                    // Update rich content
                    const newRichContent = editor.getJSON()
                    onRichContentChange?.(newRichContent)

                    // For backward compatibility, also update plain text if onChange is provided
                    if (onChange) {
                        const plainText = editor.getText()
                        onChange(plainText)
                    }
                }
                posthog.capture('markdown image uploaded', { name: fileName })
            },
            onError: (detail) => {
                posthog.capture('markdown image upload failed', { error: detail })
                lemonToast.error(`Error uploading image: ${detail}`)
            },
        })

        const editor = useEditor({
            extensions: [
                StarterKit.configure({
                    // Configure as needed
                }),
                Image.configure({
                    inline: true,
                    allowBase64: true,
                }),
                Typography,
                Placeholder.configure({
                    placeholder: editAreaProps.placeholder || 'Start typing...',
                }),
            ],
            content: '',
            editable: true,
            onUpdate: ({ editor }) => {
                // Only call callbacks if the update came from user input, not from prop sync
                if (!isUpdatingFromProp.current) {
                    // Update rich content (primary format going forward)
                    const newRichContent = editor.getJSON()
                    onRichContentChange?.(newRichContent)

                    // For backward compatibility, also update plain text if onChange is provided
                    if (onChange) {
                        const plainText = editor.getText()
                        onChange(plainText)
                    }
                }
            },
            onCreate: ({ editor }) => {
                // Priority: richContent > value (markdown/text)
                if (richContent) {
                    // Load from rich content JSON (TipTap native format)
                    editor.commands.setContent(richContent)
                } else if (value) {
                    // For legacy content, treat as plain text and let TipTap handle markdown shortcuts
                    // This is more idiomatic than parsing markdown externally
                    editor.commands.setContent(`<p>${value.replace(/\n/g, '</p><p>')}</p>`)
                }
            },
        })

        // Sync external content changes to editor (but don't recreate editor)
        useEffect(() => {
            if (editor) {
                isUpdatingFromProp.current = true

                if (richContent) {
                    // Update from rich content JSON
                    editor.commands.setContent(richContent, false)
                } else if (value !== undefined) {
                    // Update from legacy text content
                    const currentContent = editor.getText()
                    if (currentContent !== value) {
                        // Convert plain text to paragraphs, let TipTap handle formatting
                        const paragraphs = (value || '')
                            .split('\n')
                            .map((line) => (line.trim() ? `<p>${line}</p>` : '<p></p>'))
                            .join('')
                        editor.commands.setContent(paragraphs || '<p></p>', false)
                    }
                }

                // Reset flag after update completes
                setTimeout(() => {
                    isUpdatingFromProp.current = false
                }, 0)
            }
        }, [editor, richContent, value])

        // Character count for maxLength display
        const characterCount = value?.length || 0
        const isOverMaxLength = maxLength && characterCount > maxLength

        return (
            <LemonTabs
                activeKey={isPreviewShown ? 'preview' : 'write'}
                onChange={(key) => setIsPreviewShown(key === 'preview')}
                className={className}
                tabs={[
                    {
                        key: 'write',
                        label: 'Write',
                        content: (
                            <div ref={dropRef} className="LemonTextMarkdown flex flex-col gap-y-1 rounded">
                                <div
                                    ref={combinedRef}
                                    className="LemonTextArea border rounded p-2 min-h-20 relative"
                                    style={{
                                        minHeight: editAreaProps.minRows ? `${editAreaProps.minRows * 1.5}rem` : '5rem',
                                    }}
                                >
                                    <EditorContent editor={editor} className="ProseMirror-tiptap-editor" />

                                    {/* Right footer with markdown icon */}
                                    <div className="absolute bottom-2 right-2 flex items-center gap-2">
                                        <Tooltip title="Markdown formatting supported">
                                            <div>
                                                <IconMarkdown className="text-xl opacity-50" />
                                            </div>
                                        </Tooltip>
                                    </div>
                                </div>

                                {/* Toolbar */}
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <LemonFileInput
                                            key="file-upload"
                                            accept={'image/*'}
                                            multiple={false}
                                            alternativeDropTargetRef={dropRef}
                                            onChange={setFilesToUpload}
                                            loading={uploading}
                                            value={filesToUpload}
                                            showUploadedFiles={false}
                                            callToAction={
                                                <LemonButton
                                                    size="small"
                                                    icon={
                                                        uploading ? (
                                                            <Spinner className="text-lg" textColored={true} />
                                                        ) : (
                                                            <IconImage className="text-lg" />
                                                        )
                                                    }
                                                    disabledReason={
                                                        objectStorageAvailable
                                                            ? undefined
                                                            : 'Enable object storage to add images by dragging and dropping'
                                                    }
                                                    tooltip={
                                                        objectStorageAvailable
                                                            ? 'Click here or drag and drop to upload images'
                                                            : null
                                                    }
                                                />
                                            }
                                        />
                                        <EmojiPickerPopover
                                            key="emoji-picker"
                                            data-attr="lemon-tiptap-markdown-emoji-popover"
                                            onSelect={(emoji: string) => {
                                                if (editor) {
                                                    // Insert emoji at current cursor position
                                                    editor.commands.insertContent(emoji)

                                                    // Update both rich content and legacy value
                                                    const newRichContent = editor.getJSON()
                                                    onRichContentChange?.(newRichContent)

                                                    if (onChange) {
                                                        const plainText = editor.getText()
                                                        onChange(plainText)
                                                    }
                                                } else {
                                                    // Fallback to appending at the end
                                                    onChange?.((value || '') + emoji)
                                                }
                                                emojiUsed(emoji)
                                            }}
                                        />
                                    </div>

                                    {/* Character count */}
                                    {maxLength && (
                                        <div className={`text-xs ${isOverMaxLength ? 'text-danger' : 'text-muted'}`}>
                                            {characterCount} / {maxLength}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ),
                    },
                    {
                        key: 'preview',
                        label: 'Preview',
                        content:
                            richContent || value ? (
                                richContent ? (
                                    // Render rich content directly with TipTap
                                    <RichContentPreview richContent={richContent} />
                                ) : (
                                    // Fallback to markdown rendering for legacy content
                                    <LemonTextAreaMarkdown className="LemonTextArea--preview" value={value} />
                                )
                            ) : (
                                <i>Nothing to preview</i>
                            ),
                    },
                ]}
            />
        )
    }
)
