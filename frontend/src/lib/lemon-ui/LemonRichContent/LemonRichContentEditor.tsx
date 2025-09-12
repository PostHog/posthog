import './LemonRichContentEditor.scss'

import { JSONContent, generateText } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { Placeholder } from '@tiptap/extensions'
import StarterKit from '@tiptap/starter-kit'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useRef, useState } from 'react'

import { IconEye, IconImage, IconPencil } from '@posthog/icons'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { RichContentEditor } from 'lib/components/RichContentEditor'
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
import { uuid } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export type LemonRichContentEditorProps = {
    initialContent?: JSONContent
    onChange: (content: JSONContent) => void
    className?: string
}

const DEFAULT_INITIAL_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
            content: [
                {
                    type: 'text',
                    text: 'This is my content',
                },
            ],
        },
    ],
}

const extensions = [
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

export function LemonRichContentEditor({
    logicKey = uuid(),
    initialContent,
    placeholder,
    onChange,
    onCreate,
}: {
    logicKey?: string
    initialContent?: JSONContent
    placeholder?: string
    onChange: (content: JSONContent) => void
    onCreate?: (editor: RichContentEditorType) => void
}): JSX.Element {
    const [isPreviewShown, setIsPreviewShown] = useState<boolean>(false)
    const [content, setContent] = useState<JSONContent | undefined>(initialContent ?? DEFAULT_INITIAL_CONTENT)
    const [ttEditor, setTTEditor] = useState<TTEditor | null>(null)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)

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
        <div ref={dropRef} className="LemonRichContentEditor flex flex-col border rounded divide-y mt-4">
            {isPreviewShown ? (
                <RichContent content={content} />
            ) : (
                <RichContentEditor
                    logicKey={logicKey}
                    extensions={[...extensions, Placeholder.configure({ placeholder })]}
                    autoFocus
                    initialContent={content}
                    onUpdate={(newContent) => {
                        setContent(newContent)
                        onChange(newContent)
                    }}
                    onCreate={(editor) => {
                        if (onCreate) {
                            onCreate(createEditor(editor))
                        }
                        setTTEditor(editor)
                    }}
                    className="p-2"
                />
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
                    <LemonButton
                        size="small"
                        active={!isPreviewShown}
                        onClick={() => {
                            setIsPreviewShown(false)
                            ttEditor?.setOptions({ editable: true })
                        }}
                    >
                        <IconPencil />
                    </LemonButton>
                    <LemonButton
                        size="small"
                        active={isPreviewShown}
                        onClick={() => {
                            setIsPreviewShown(true)
                            ttEditor?.setOptions({ editable: false })
                        }}
                    >
                        <IconEye />
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

const RichContent = ({ content }: { content?: JSONContent }): JSX.Element => {
    const text = useMemo(() => {
        const hasContent = content && content.content && content.content[0].content
        const text = hasContent
            ? generateText(content, extensions, {
                  textSerializers: {
                      [RichContentNodeType.Mention]: ({ node }) => `@member:${node.attrs.id}`,
                  },
              })
            : ''
        return text.length === 0 ? '_Nothing to preview_' : text
    }, [content])

    return <TextContent text={text} className="p-2" />
}
