import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { useCallback, useRef, useState } from 'react'

import { IconImage, IconMarkdownFilled } from '@posthog/icons'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea, LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export const LemonTextAreaMarkdown = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(
    function LemonTextAreaMarkdown({ value, onChange, className, ...editAreaProps }, ref): JSX.Element {
        const { objectStorageAvailable } = useValues(preflightLogic)
        const { emojiUsed } = useActions(emojiUsageLogic)

        const [isPreviewShown, setIsPreviewShown] = useState(false)
        const dropRef = useRef<HTMLDivElement>(null)

        // we need a local ref so we can insert emojis at the cursor's location
        const textAreaRef = useRef<HTMLTextAreaElement>(null)
        const combinedRef = useCallback(
            (element: HTMLTextAreaElement | null) => {
                // Store reference in our local ref
                ;(textAreaRef as React.MutableRefObject<HTMLTextAreaElement | null>).current = element
                // Forward to the original ref
                if (typeof ref === 'function') {
                    ref(element)
                } else if (ref) {
                    ;(ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = element
                }
            },
            [ref]
        )

        const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
            onUpload: (url, fileName) => {
                onChange?.(value + `\n\n![${fileName}](${url})`)
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
                            <div ref={dropRef} className="LemonTextMarkdown flex flex-col gap-y-1 rounded">
                                <LemonTextArea
                                    ref={combinedRef}
                                    {...editAreaProps}
                                    autoFocus
                                    value={value}
                                    onChange={onChange}
                                    rightFooter={
                                        <>
                                            <Tooltip title="Markdown formatting supported">
                                                <div>
                                                    <IconMarkdownFilled className="text-xl" />
                                                </div>
                                            </Tooltip>
                                        </>
                                    }
                                    actions={[
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
                                        />,
                                        <EmojiPickerPopover
                                            key="emoj-picker"
                                            data-attr="lemon-text-area-markdown-emoji-popover"
                                            onSelect={(emoji: string) => {
                                                const textArea = textAreaRef.current
                                                if (textArea) {
                                                    const start = textArea.selectionStart || 0
                                                    const end = textArea.selectionEnd || 0
                                                    const currentValue = value || ''
                                                    const newValue =
                                                        currentValue.slice(0, start) + emoji + currentValue.slice(end)
                                                    onChange?.(newValue)

                                                    // Set cursor position after the emoji
                                                    setTimeout(() => {
                                                        textArea.focus()
                                                        textArea.setSelectionRange(
                                                            start + emoji.length,
                                                            start + emoji.length
                                                        )
                                                    }, 0)
                                                } else {
                                                    // Fallback to appending at the end
                                                    onChange?.((value || '') + emoji)
                                                }
                                                emojiUsed(emoji)
                                            }}
                                        />,
                                    ]}
                                />
                            </div>
                        ),
                    },
                    {
                        key: 'preview',
                        label: 'Preview',
                        content: value ? (
                            <TextContent text={value} className="LemonTextArea--preview" />
                        ) : (
                            <i>Nothing to preview</i>
                        ),
                    },
                ]}
            />
        )
    }
)
