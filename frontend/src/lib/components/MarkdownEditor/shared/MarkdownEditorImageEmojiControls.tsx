import type { Editor } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import type { RefObject } from 'react'

import { IconImage, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMarkdownEditorImageUpload } from './useMarkdownEditorImageUpload'

/** Rich toolbar: “Markdown supported” indicator — place at the trailing edge of the bar. */
export function MarkdownEditorMarkdownFormatHintGlyph(): JSX.Element {
    return (
        <Tooltip title="Markdown formatting supported">
            <span className="inline-flex size-[2rem] shrink-0 items-center justify-center text-secondary [&_svg]:size-5">
                <IconMarkdownFilled />
            </span>
        </Tooltip>
    )
}

export type MarkdownEditorImageEmojiControlsProps = {
    editor: Editor | null
    alternativeDropTargetRef: RefObject<HTMLElement | null>
    /** Pass through to EmojiPickerPopover */
    emojiPopoverDataAttr: string
    showImageUpload?: boolean
    showEmoji?: boolean
}

/**
 * Image upload + emoji picker shared by `RichMarkdownEditor` (toolbar) and `RichMarkdownEditorBubbleMenu`.
 */
export function MarkdownEditorImageEmojiControls({
    editor,
    alternativeDropTargetRef,
    emojiPopoverDataAttr,
    showImageUpload = true,
    showEmoji = true,
}: MarkdownEditorImageEmojiControlsProps): JSX.Element | null {
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)
    const { setFilesToUpload, filesToUpload, uploading } = useMarkdownEditorImageUpload(editor)

    if (!showImageUpload && !showEmoji) {
        return null
    }

    return (
        <div className="flex items-center gap-0.5">
            {showImageUpload ? (
                <LemonFileInput
                    accept="image/*"
                    multiple={false}
                    alternativeDropTargetRef={alternativeDropTargetRef as RefObject<HTMLElement>}
                    onChange={setFilesToUpload}
                    loading={uploading}
                    value={filesToUpload}
                    showUploadedFiles={false}
                    callToAction={
                        <LemonButton
                            size="small"
                            icon={uploading ? <Spinner textColored /> : <IconImage />}
                            disabledReason={
                                objectStorageAvailable
                                    ? undefined
                                    : 'Enable object storage to add images by dragging and dropping'
                            }
                            tooltip={objectStorageAvailable ? 'Click here or drag and drop to upload images' : null}
                        />
                    }
                />
            ) : null}
            {showEmoji ? (
                <EmojiPickerPopover
                    data-attr={emojiPopoverDataAttr}
                    onSelect={(emoji: string) => {
                        editor?.chain().focus().insertContent(emoji).run()
                        emojiUsed(emoji)
                    }}
                />
            ) : null}
        </div>
    )
}
