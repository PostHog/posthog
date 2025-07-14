import { useValues } from 'kea'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconMarkdown, IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea, LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import posthog from 'posthog-js'
import React, { useRef, useState } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { IconShare } from '@posthog/icons'
import { Popover } from 'lib/lemon-ui/Popover'
import { EmojiPicker } from 'frimousse'

export function MyEmojiPicker({ onSelect }: { onSelect: (s: string) => void }): JSX.Element {
    return (
        <EmojiPicker.Root
            className="isolate flex h-[368px] w-fit flex-col bg-white dark:bg-neutral-900"
            onEmojiSelect={({ emoji }) => {
                onSelect(emoji)
            }}
        >
            <EmojiPicker.Search className="z-10 mx-2 mt-2 appearance-none rounded-md bg-neutral-100 px-2.5 py-2 text-sm dark:bg-neutral-800" />
            <EmojiPicker.Viewport className="relative flex-1 outline-hidden">
                <EmojiPicker.Loading className="absolute inset-0 flex items-center justify-center text-neutral-400 text-sm dark:text-neutral-500">
                    Loading…
                </EmojiPicker.Loading>
                <EmojiPicker.Empty className="absolute inset-0 flex items-center justify-center text-neutral-400 text-sm dark:text-neutral-500">
                    No emoji found.
                </EmojiPicker.Empty>
                <EmojiPicker.List
                    className="select-none pb-1.5"
                    components={{
                        CategoryHeader: ({ category, ...props }) => (
                            <div
                                className="bg-white px-3 pt-3 pb-1.5 font-medium text-neutral-600 text-xs dark:bg-neutral-900 dark:text-neutral-400"
                                {...props}
                            >
                                {category.label}
                            </div>
                        ),
                        Row: ({ children, ...props }) => (
                            <div className="scroll-my-1.5 px-1.5" {...props}>
                                {children}
                            </div>
                        ),
                        Emoji: ({ emoji, ...props }) => (
                            <button
                                className="flex size-8 items-center justify-center rounded-md text-lg data-[active]:bg-neutral-100 dark:data-[active]:bg-neutral-800"
                                {...props}
                            >
                                {emoji.emoji}
                            </button>
                        ),
                    }}
                />
            </EmojiPicker.Viewport>
        </EmojiPicker.Root>
    )
}

export const LemonTextAreaMarkdown = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(
    function LemonTextAreaMarkdown({ value, onChange, className, ...editAreaProps }, ref): JSX.Element {
        const { objectStorageAvailable } = useValues(preflightLogic)

        const [isPreviewShown, setIsPreviewShown] = useState(false)
        const dropRef = useRef<HTMLDivElement>(null)

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

        const [emojiPickerOpen, setEmojiPickerOpen] = useState(false)

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
                                    ref={ref}
                                    {...editAreaProps}
                                    autoFocus
                                    value={value}
                                    onChange={onChange}
                                    rightFooter={
                                        <>
                                            <Tooltip title="Markdown formatting supported">
                                                <div>
                                                    <IconMarkdown className="text-xl" />
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
                                            callToAction={
                                                objectStorageAvailable ? (
                                                    <Tooltip title="Click here or drag and drop to upload images">
                                                        <div className="rounded hover:bg-fill-button-tertiary-hover px-1 py-0.5">
                                                            {' '}
                                                            <IconUploadFile className="text-xl" />
                                                        </div>
                                                    </Tooltip>
                                                ) : (
                                                    <Tooltip title="Enable object storage to add images by dragging and dropping">
                                                        <div className="rounded px-1 py-0.5">
                                                            {' '}
                                                            <IconUploadFile className="text-xl" />
                                                        </div>
                                                    </Tooltip>
                                                )
                                            }
                                        />,
                                        <Popover
                                            onClickOutside={() => setEmojiPickerOpen(false)}
                                            visible={emojiPickerOpen}
                                            overlay={
                                                <MyEmojiPicker
                                                    onSelect={(emoji) => {
                                                        onChange?.(value + ' ' + emoji)
                                                        setEmojiPickerOpen(false)
                                                    }}
                                                />
                                            }
                                        >
                                            <LemonButton
                                                key="emoji"
                                                icon={<IconShare />}
                                                onClick={() => {
                                                    setEmojiPickerOpen(!emojiPickerOpen)
                                                }}
                                            />
                                        </Popover>,
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
