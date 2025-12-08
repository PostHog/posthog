import './LemonRichContentEditor.scss'

import { Extensions, JSONContent, TextSerializer } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { Placeholder } from '@tiptap/extensions'
import { EditorContent } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import StarterKit from '@tiptap/starter-kit'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { IconEye, IconImage, IconPencil } from '@posthog/icons'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { CommandEnterExtension } from 'lib/components/RichContentEditor/CommandEnterExtension'
import { MentionsExtension } from 'lib/components/RichContentEditor/MentionsExtension'
import { RichContentNodeMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { RichContentEditorType, RichContentNodeType, TTEditor } from 'lib/components/RichContentEditor/types'
import { createEditor } from 'lib/components/RichContentEditor/utils'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconBold, IconItalic } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export type LemonRichContentEditorProps = {
    logicKey?: string
    initialContent?: JSONContent | null
    placeholder?: string
    onCreate?: (editor: RichContentEditorType) => void
    onUpdate?: (isEmpty: boolean) => void
    onPressCmdEnter?: () => void
    disabled?: boolean
    minRows?: number
    /** Enable rich text formatting (bold, italic, links, lists). Shows a bubble menu on text selection. */
    enableRichFormatting?: boolean
    /** Enable heading formatting (H1, H2). Requires enableRichFormatting. */
    enableHeadings?: boolean
    /** Disable @mentions. */
    disableMentions?: boolean
    /** Disable the emoji picker. */
    disableEmoji?: boolean
    classNames?: string
}

const DEFAULT_INITIAL_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
            content: [],
        },
    ],
}

export const DEFAULT_EXTENSIONS = [
    MentionsExtension,
    RichContentNodeMention,
    ExtensionDocument,
    StarterKit.configure({
        document: false,
        link: false,
        heading: false,
        blockquote: false,
        bold: false,
        bulletList: false,
        code: false,
        codeBlock: false,
        hardBreak: false,
        dropcursor: false,
        gapcursor: false,
        horizontalRule: false,
        italic: false,
        listItem: false,
        listKeymap: false,
        orderedList: false,
        strike: false,
        underline: false,
    }),
]

type ExtensionOptions = {
    enableRichFormatting?: boolean
    enableHeadings?: boolean
    disableMentions?: boolean
    placeholder?: string
    onPressCmdEnter?: () => void
}

const HeadingIcon = ({ level }: { level: number }): JSX.Element => (
    <div className="text-xs font-semibold">
        H<span className="text-[10px] font-bold">{level}</span>
    </div>
)

function buildExtensions({
    enableRichFormatting,
    enableHeadings,
    disableMentions,
    placeholder,
    onPressCmdEnter,
}: ExtensionOptions): Extensions {
    const extensions: Extensions = [ExtensionDocument]

    if (!disableMentions) {
        extensions.push(MentionsExtension, RichContentNodeMention)
    }

    if (enableRichFormatting) {
        extensions.push(
            StarterKit.configure({
                document: false,
                blockquote: false,
                code: false,
                codeBlock: false,
                horizontalRule: false,
                heading: enableHeadings ? { levels: [1, 2] } : false,
            })
        )
    } else {
        extensions.push(
            StarterKit.configure({
                document: false,
                link: false,
                heading: false,
                blockquote: false,
                bold: false,
                bulletList: false,
                code: false,
                codeBlock: false,
                hardBreak: false,
                dropcursor: false,
                gapcursor: false,
                horizontalRule: false,
                italic: false,
                listItem: false,
                listKeymap: false,
                orderedList: false,
                strike: false,
                underline: false,
            })
        )
    }

    if (placeholder) {
        extensions.push(Placeholder.configure({ placeholder }))
    }

    if (onPressCmdEnter) {
        extensions.push(CommandEnterExtension.configure({ onPressCmdEnter }))
    }

    return extensions
}

export const serializationOptions: { textSerializers?: Record<string, TextSerializer> } = {
    textSerializers: { [RichContentNodeType.Mention]: ({ node }) => `@member:${node.attrs.id}` },
}

export function RichContentPreview({
    content,
    className,
}: {
    content: JSONContent | null
    className?: string
}): JSX.Element {
    const editor = useRichContentEditor({
        extensions: [...DEFAULT_EXTENSIONS],
        // preview isn't editable
        disabled: true,
        initialContent: content ?? DEFAULT_INITIAL_CONTENT,
    })
    return <RichContent editor={editor} className={className} />
}

export function LemonRichContentEditor({
    initialContent,
    placeholder,
    onCreate,
    onUpdate,
    onPressCmdEnter,
    classNames,
    disabled = false,
    minRows,
    enableRichFormatting = false,
    enableHeadings = false,
    disableMentions = false,
}: LemonRichContentEditorProps): JSX.Element {
    const [isPreviewShown, setIsPreviewShown] = useState<boolean>(false)
    const [ttEditor, setTTEditor] = useState<TTEditor | null>(null)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)
    const editor = useRichContentEditor({
        extensions: buildExtensions({
            enableRichFormatting,
            enableHeadings,
            disableMentions,
            placeholder,
            onPressCmdEnter,
        }),
        disabled,
        initialContent: initialContent ?? DEFAULT_INITIAL_CONTENT,
        onCreate: (editor) => {
            if (onCreate) {
                onCreate(createEditor(editor))
            }
            setTTEditor(editor)
        },
        onUpdate: () => {
            if (onUpdate && ttEditor) {
                onUpdate(ttEditor.isEmpty)
            }
        },
    })

    const dropRef = useRef<HTMLDivElement>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            if (ttEditor) {
                ttEditor.commands.insertContent(`\n\n![${fileName}](${url})`)
            }
            posthog.capture('rich text image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('rich text image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    return (
        <div
            ref={dropRef}
            className={cn('LemonRichContentEditor flex flex-col border rounded divide-y mt-4', classNames)}
        >
            {isPreviewShown && ttEditor ? (
                <RichContent editor={ttEditor} className="bg-fill-input" />
            ) : (
                <>
                    <EditorContent
                        editor={editor}
                        className="RichContentEditor p-2"
                        autoFocus
                        style={minRows ? { minHeight: `${minRows * 1.5}em` } : undefined}
                    />
                    {enableRichFormatting && editor && (
                        <BubbleMenu
                            editor={editor}
                            options={{ placement: 'top-start' }}
                            shouldShow={({ editor: ed, state, from, to }) => {
                                return ed.isEditable && state.doc.textBetween(from, to).length > 0
                            }}
                        >
                            <div className="flex bg-surface-primary rounded border items-center p-0.5 gap-0.5 shadow-lg">
                                {enableHeadings && (
                                    <>
                                        <LemonButton
                                            size="xsmall"
                                            active={editor.isActive('heading', { level: 1 })}
                                            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                                            icon={<HeadingIcon level={1} />}
                                        />
                                        <LemonButton
                                            size="xsmall"
                                            active={editor.isActive('heading', { level: 2 })}
                                            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                                            icon={<HeadingIcon level={2} />}
                                        />
                                    </>
                                )}
                                <LemonButton
                                    size="xsmall"
                                    active={editor.isActive('bold')}
                                    onClick={() => editor.chain().focus().toggleBold().run()}
                                    icon={<IconBold />}
                                />
                                <LemonButton
                                    size="xsmall"
                                    active={editor.isActive('italic')}
                                    onClick={() => editor.chain().focus().toggleItalic().run()}
                                    icon={<IconItalic />}
                                />
                            </div>
                        </BubbleMenu>
                    )}
                </>
            )}
            <div className="flex justify-between p-0.5">
                <div className="flex">
                    {!isPreviewShown && (
                        <LemonFileInput
                            key="file-upload"
                            accept={'image/*'}
                            multiple={false}
                            alternativeDropTargetRef={dropRef}
                            onChange={setFilesToUpload}
                            loading={uploading}
                            value={filesToUpload}
                            showUploadedFiles={false}
                            disabledReason={
                                objectStorageAvailable
                                    ? undefined
                                    : 'Enable object storage to add images by dragging and dropping'
                            }
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
                                    tooltip={
                                        objectStorageAvailable ? 'Click here or drag and drop to upload images' : null
                                    }
                                />
                            }
                        />
                    )}
                    {!isPreviewShown && (
                        <EmojiPickerPopover
                            key="emoj-picker"
                            data-attr="lemon-rich-text-editor-emoji-popover"
                            onSelect={(emoji: string) => {
                                if (ttEditor) {
                                    ttEditor.commands.insertContent(emoji)
                                    emojiUsed(emoji)
                                }
                            }}
                        />
                    )}
                </div>
                <div className="flex items-center gap-0.5">
                    <LemonButton size="small" active={!isPreviewShown} onClick={() => setIsPreviewShown(false)}>
                        <IconPencil />
                    </LemonButton>
                    <LemonButton size="small" active={isPreviewShown} onClick={() => setIsPreviewShown(true)}>
                        <IconEye />
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

const RichContent = ({ editor, className }: { editor: TTEditor; className?: string }): JSX.Element => {
    const text = editor?.getText(serializationOptions)

    return (
        <TextContent
            text={text && text.length != 0 ? text : '_Nothing to preview_'}
            className={cn('p-2 rounded-t', className)}
        />
    )
}
