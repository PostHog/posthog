import './RichMarkdownEditor.scss'

import { JSONContent } from '@tiptap/core'
import { EditorContent, Extensions } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import { IconArrowLeft, IconArrowRight, IconCode, IconImage, IconList, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

type RichMarkdownEditorProps = {
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
}

function getHeadingLabel(editor: ReturnType<typeof useRichContentEditor> | null): string {
    if (editor?.isActive('heading', { level: 1 })) {
        return 'H1'
    }
    if (editor?.isActive('heading', { level: 2 })) {
        return 'H2'
    }
    if (editor?.isActive('heading', { level: 3 })) {
        return 'H3'
    }
    return 'H'
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
}: RichMarkdownEditorProps): JSX.Element {
    const [activeTab, setActiveTab] = useState<'write' | 'preview' | 'markdown'>('write')
    const [linkUrl, setLinkUrl] = useState('')
    const [showLinkPopover, setShowLinkPopover] = useState(false)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)
    const dropRef = useRef<HTMLDivElement>(null)
    const lastSyncedMarkdownRef = useRef(value || '')

    const syncMarkdownFromEditor = (nextMarkdown: string, options?: { force?: boolean }): void => {
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
    }

    const editor = useRichContentEditor({
        extensions,
        initialContent: markdownToDoc(value),
        onUpdate: (content) => syncMarkdownFromEditor(docToMarkdown(content)),
    })

    useEffect(() => {
        if (editor) {
            editor.commands.focus()
        }
    }, [editor])

    useEffect(() => {
        lastSyncedMarkdownRef.current = value || ''
    }, [value])

    useEffect(() => {
        if (!editor) {
            return
        }

        const currentEditorMarkdown = docToMarkdown(editor.getJSON())
        const incomingMarkdown = value || ''
        if (currentEditorMarkdown !== incomingMarkdown) {
            editor.commands.setContent(markdownToDoc(incomingMarkdown), { emitUpdate: false })
        }
    }, [editor, value, docToMarkdown, markdownToDoc])

    useEffect(() => {
        if (!editor) {
            return
        }

        const editorElement = (editor as { view?: { dom?: HTMLElement } }).view?.dom
        const formElement = editorElement?.closest('form')
        if (!formElement) {
            return
        }

        // Must be effect-scoped so the submit capture listener is correctly cleaned up/rebound.
        // Capture-phase submit sync prevents save races by flushing latest editor state before
        // the form submit pipeline reads values (especially important for non-typing updates).
        const handleFormSubmitCapture = (): void => {
            syncMarkdownFromEditor(docToMarkdown(editor.getJSON()), { force: true })
        }

        formElement.addEventListener('submit', handleFormSubmitCapture, true)
        return () => {
            formElement.removeEventListener('submit', handleFormSubmitCapture, true)
        }
    }, [editor, docToMarkdown])

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            if (editor) {
                editor.chain().focus().setImage({ src: url, alt: fileName }).run()
            }
            posthog.capture('markdown image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('markdown image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const currentMarkdown = editor ? docToMarkdown(editor.getJSON()) : value || ''
    const isAtCharacterLimit = currentMarkdown.length > maxLength
    const hasExistingLink = editor?.isActive('link') ?? false

    const setLink = (): void => {
        if (!linkUrl) {
            return
        }
        editor?.chain().focus().setLink({ href: linkUrl }).run()
        setShowLinkPopover(false)
        setLinkUrl('')
    }

    const removeLink = (): void => {
        editor?.chain().focus().unsetLink().run()
        setShowLinkPopover(false)
        setLinkUrl('')
    }

    const openLinkPopover = (): void => {
        const previousUrl = editor?.getAttributes('link').href || ''
        setLinkUrl(previousUrl)
        setShowLinkPopover(true)
    }

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
                            <div className="flex items-center gap-0.5 p-1 border-b overflow-x-auto whitespace-nowrap">
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
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Heading 1',
                                            onClick: () => editor?.chain().focus().toggleHeading({ level: 1 }).run(),
                                            active: !!editor?.isActive('heading', { level: 1 }),
                                        },
                                        {
                                            label: 'Heading 2',
                                            onClick: () => editor?.chain().focus().toggleHeading({ level: 2 }).run(),
                                            active: !!editor?.isActive('heading', { level: 2 }),
                                        },
                                        {
                                            label: 'Heading 3',
                                            onClick: () => editor?.chain().focus().toggleHeading({ level: 3 }).run(),
                                            active: !!editor?.isActive('heading', { level: 3 }),
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="small"
                                        active={
                                            editor?.isActive('heading', { level: 1 }) ||
                                            editor?.isActive('heading', { level: 2 }) ||
                                            editor?.isActive('heading', { level: 3 })
                                        }
                                        tooltip="Headings"
                                    >
                                        {getHeadingLabel(editor)}
                                    </LemonButton>
                                </LemonMenu>
                                <LemonDivider vertical className="mx-1 self-stretch" />
                                <LemonButton
                                    size="small"
                                    active={editor?.isActive('bold')}
                                    onClick={() => editor?.chain().focus().toggleBold().run()}
                                    icon={<IconBold />}
                                    tooltip="Bold"
                                />
                                <LemonButton
                                    size="small"
                                    active={editor?.isActive('italic')}
                                    onClick={() => editor?.chain().focus().toggleItalic().run()}
                                    icon={<IconItalic />}
                                    tooltip="Italic"
                                />
                                <LemonButton
                                    size="small"
                                    active={editor?.isActive('underline')}
                                    onClick={() => editor?.chain().focus().toggleUnderline().run()}
                                    tooltip="Underline"
                                >
                                    <span className="font-semibold underline">U</span>
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    active={editor?.isActive('code')}
                                    onClick={() => editor?.chain().focus().toggleCode().run()}
                                    icon={<IconCode />}
                                    tooltip="Inline code"
                                />
                                <LemonButton
                                    size="small"
                                    active={editor?.isActive('codeBlock')}
                                    onClick={() => editor?.chain().focus().toggleCodeBlock().run()}
                                    tooltip="Code block"
                                >
                                    {`</>`}
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    active={editor?.isActive('blockquote')}
                                    onClick={() => editor?.chain().focus().toggleBlockquote().run()}
                                    tooltip="Blockquote"
                                >
                                    "
                                </LemonButton>
                                <LemonDivider vertical className="mx-1 self-stretch" />
                                <LemonMenu
                                    items={[
                                        {
                                            label: 'Bullet list',
                                            icon: <IconList />,
                                            onClick: () => editor?.chain().focus().toggleBulletList().run(),
                                            active: !!editor?.isActive('bulletList'),
                                        },
                                        {
                                            label: 'Numbered list',
                                            icon: (
                                                <span className="inline-flex w-4 justify-center text-xs font-semibold">
                                                    1.
                                                </span>
                                            ),
                                            onClick: () => editor?.chain().focus().toggleOrderedList().run(),
                                            active: !!editor?.isActive('orderedList'),
                                        },
                                        {
                                            label: 'Task list',
                                            icon: <span className="inline-flex w-4 justify-center text-xs">[ ]</span>,
                                            onClick: () => editor?.chain().focus().toggleTaskList().run(),
                                            active: !!editor?.isActive('taskList'),
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        size="small"
                                        active={
                                            editor?.isActive('bulletList') ||
                                            editor?.isActive('orderedList') ||
                                            editor?.isActive('taskList')
                                        }
                                        icon={<IconList />}
                                        tooltip="Lists"
                                    />
                                </LemonMenu>
                                <Popover
                                    visible={showLinkPopover}
                                    onClickOutside={() => setShowLinkPopover(false)}
                                    overlay={
                                        <div className="p-2 flex flex-col gap-2 min-w-64">
                                            <LemonInput
                                                size="small"
                                                placeholder="https://..."
                                                value={linkUrl}
                                                onChange={setLinkUrl}
                                                onPressEnter={setLink}
                                                autoFocus
                                                fullWidth
                                            />
                                            <div className="flex gap-2 justify-end">
                                                {hasExistingLink && (
                                                    <LemonButton size="small" status="danger" onClick={removeLink}>
                                                        Remove
                                                    </LemonButton>
                                                )}
                                                <LemonButton
                                                    size="small"
                                                    type="primary"
                                                    onClick={setLink}
                                                    disabledReason={!linkUrl ? 'Enter a URL' : undefined}
                                                >
                                                    {hasExistingLink ? 'Update' : 'Set'}
                                                </LemonButton>
                                            </div>
                                        </div>
                                    }
                                >
                                    <LemonButton
                                        size="small"
                                        active={editor?.isActive('link')}
                                        icon={<IconLink />}
                                        onClick={openLinkPopover}
                                        tooltip="Link"
                                    />
                                </Popover>
                                <div className="ml-auto flex items-center gap-0.5">
                                    <Tooltip title="Markdown formatting supported">
                                        <div>
                                            <IconMarkdownFilled className="text-xl text-secondary" />
                                        </div>
                                    </Tooltip>
                                    <LemonFileInput
                                        accept="image/*"
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
                                        data-attr="rich-markdown-editor-emoji-popover"
                                        onSelect={(emoji: string) => {
                                            if (editor) {
                                                editor.chain().focus().insertContent(emoji).run()
                                                emojiUsed(emoji)
                                            }
                                        }}
                                    />
                                </div>
                            </div>
                            <EditorContent
                                editor={editor}
                                className="RichMarkdownEditor__content px-3 py-2 overflow-auto"
                                style={{ minHeight: `${minRows * 1.5}em`, maxHeight: `${maxRows * 1.5}em` }}
                                data-attr={dataAttr}
                            />
                            <div
                                className={`px-3 py-1 border-t bg-surface-primary text-xs text-right shrink-0 ${
                                    isAtCharacterLimit ? 'text-danger' : 'text-muted'
                                }`}
                            >
                                {currentMarkdown.length}/{maxLength} characters
                                {isAtCharacterLimit ? ' (limit reached)' : ''}
                            </div>
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
