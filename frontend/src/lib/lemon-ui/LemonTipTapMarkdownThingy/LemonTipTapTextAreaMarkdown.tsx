import './LemonTipTapTextAreaMarkdown.scss'

import { JSONContent, generateText } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import StarterKit from '@tiptap/starter-kit'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useRef, useState } from 'react'

import { IconImage } from '@posthog/icons'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { RichContentEditor } from 'lib/components/RichContentEditor'
import { TTEditor } from 'lib/components/RichContentEditor/types'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export type LemonTipTapTextAreaMarkdownProps = {
    initialContent?: JSONContent
    onChange: (content: JSONContent) => void
    className?: string
}

const extensions = [
    ExtensionDocument,
    StarterKit.configure({
        document: false,
        gapcursor: false,
        link: false,
        heading: false,
    }),
]

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

export function LemonTipTapTextAreaMarkdown({
    content = DEFAULT_INITIAL_CONTENT,
    onChange,
    className,
}: {
    content?: JSONContent
    onChange: (content: JSONContent) => void
    className?: string
}): JSX.Element {
    const [ttEditor, setTTEditor] = useState<TTEditor | null>(null)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)

    const [isPreviewShown, setIsPreviewShown] = useState(false)
    const dropRef = useRef<HTMLDivElement>(null)

    const text = useMemo(() => {
        const hasContent = content && content.content && content.content[0].content
        return hasContent ? generateText(content, extensions) : ''
    }, [content])

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            if (ttEditor) {
                ttEditor.commands.insertContent(`\n\n![${fileName}](${url})`)
            }
            posthog.capture('markdown image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('markdown image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

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
                        <div ref={dropRef} className="LemonTipTapMarkdown flex flex-col border rounded divide-y">
                            <RichContentEditor
                                logicKey="markdown-editor"
                                extensions={extensions}
                                autoFocus
                                initialContent={content}
                                onUpdate={(newContent) => {
                                    // setContent(newContent)
                                    onChange(newContent)
                                }}
                                onCreate={setTTEditor}
                                className="p-2"
                            />
                            <div className="flex">
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
                                    key="emoj-picker"
                                    data-attr="lemon-text-area-markdown-emoji-popover"
                                    onSelect={(emoji: string) => {
                                        if (ttEditor) {
                                            ttEditor.commands.insertContent(emoji)
                                            emojiUsed(emoji)
                                        }
                                    }}
                                />
                            </div>
                        </div>
                    ),
                },
                {
                    key: 'preview',
                    label: 'Preview',
                    content: content ? <TextContent text={text} /> : <i>Nothing to preview</i>,
                },
            ]}
        />
    )
}
