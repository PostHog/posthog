import { useActions, useValues } from 'kea'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconMarkdown } from 'lib/lemon-ui/icons'
import { IconImage } from '@posthog/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea, LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'
import React, { useRef, useState, useCallback } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import Fuse from 'fuse.js'

export const LemonTextAreaMarkdown = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(
    function LemonTextAreaMarkdown({ value, onChange, className, ...editAreaProps }, ref): JSX.Element {
        const { objectStorageAvailable } = useValues(preflightLogic)
        const { emojiUsed } = useActions(emojiUsageLogic)
        const { meFirstMembers } = useValues(membersLogic)

        const [isPreviewShown, setIsPreviewShown] = useState(false)
        const dropRef = useRef<HTMLDivElement>(null)

        // Mentions state
        const [mentionsOpen, setMentionsOpen] = useState(false)
        const [mentionsQuery, setMentionsQuery] = useState('')
        const [mentionsPosition, setMentionsPosition] = useState({ top: 0, left: 0 })
        const [mentionsStartIndex, setMentionsStartIndex] = useState(0)
        const [selectedMentionIndex, setSelectedMentionIndex] = useState(0)

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

        // Helper function to detect @ mentions
        const detectMentions = useCallback((text: string, cursorPosition: number) => {
            const beforeCursor = text.slice(0, cursorPosition)
            const lastAtIndex = beforeCursor.lastIndexOf('@')

            if (lastAtIndex === -1) {
                return null
            }

            // Check if there's a word boundary before the @
            const charBeforeAt = beforeCursor[lastAtIndex - 1]
            if (charBeforeAt && /\w/.test(charBeforeAt)) {
                return null
            }

            // Extract the query after @
            const queryAfterAt = beforeCursor.slice(lastAtIndex + 1)

            // Check if the query contains whitespace or newlines (invalid mention)
            if (/\s/.test(queryAfterAt)) {
                return null
            }

            return {
                startIndex: lastAtIndex,
                query: queryAfterAt,
            }
        }, [])

        // Helper function to get cursor position in pixels
        const getCursorPosition = useCallback((textarea: HTMLTextAreaElement, cursorIndex: number) => {
            const div = document.createElement('div')
            const style = getComputedStyle(textarea)

            // Copy textarea styles to div
            ;[
                'font-family',
                'font-size',
                'font-weight',
                'line-height',
                'letter-spacing',
                'padding-left',
                'padding-top',
                'padding-right',
                'padding-bottom',
                'border-left-width',
                'border-top-width',
                'border-right-width',
                'border-bottom-width',
                'white-space',
                'word-wrap',
                'word-break',
                'box-sizing',
            ].forEach((prop) => {
                div.style[prop as any] = style[prop as any]
            })

            div.style.position = 'absolute'
            div.style.visibility = 'hidden'
            div.style.whiteSpace = 'pre-wrap'
            div.style.width = style.width
            div.style.height = style.height
            div.style.overflow = 'hidden'
            div.style.zIndex = '-1000'

            const text = textarea.value
            const textBeforeCursor = text.slice(0, cursorIndex)
            const textAfterCursor = text.slice(cursorIndex)

            div.innerHTML = textBeforeCursor + '<span id="cursor-position"></span>' + textAfterCursor

            // Position the div at the same location as the textarea
            const textareaRect = textarea.getBoundingClientRect()
            div.style.top = textareaRect.top + window.scrollY + 'px'
            div.style.left = textareaRect.left + window.scrollX + 'px'

            document.body.appendChild(div)

            const cursorSpan = div.querySelector('#cursor-position')
            const cursorRect = cursorSpan?.getBoundingClientRect()

            const position = {
                top: (cursorRect?.top || 0) - textareaRect.top + textarea.scrollTop,
                left: (cursorRect?.left || 0) - textareaRect.left + textarea.scrollLeft,
            }

            document.body.removeChild(div)
            return position
        }, [])

        // Filter members for mentions
        const filteredMembers = React.useMemo(() => {
            const members = !mentionsQuery
                ? meFirstMembers.slice(0, 10) // Show first 10 members by default
                : new Fuse(meFirstMembers, {
                      keys: ['user.first_name', 'user.last_name', 'user.email'],
                      threshold: 0.3,
                  })
                      .search(mentionsQuery)
                      .map((result) => result.item)
                      .slice(0, 10)

            // Reset selection when members change
            setSelectedMentionIndex(0)
            return members
        }, [meFirstMembers, mentionsQuery])

        // Handle mention selection
        const selectMention = useCallback(
            (member: any) => {
                const mentionText = `@${member.user.first_name} ${member.user.last_name}`
                const currentValue = value || ''
                const beforeMention = currentValue.slice(0, mentionsStartIndex)
                const afterMention = currentValue.slice(textAreaRef.current?.selectionStart || 0)
                const newValue = beforeMention + mentionText + afterMention

                onChange?.(newValue)
                setMentionsOpen(false)

                // Set cursor position after mention
                setTimeout(() => {
                    const textarea = textAreaRef.current
                    if (textarea) {
                        textarea.focus()
                        const cursorPos = beforeMention.length + mentionText.length
                        textarea.setSelectionRange(cursorPos, cursorPos)
                    }
                }, 0)
            },
            [value, onChange, mentionsStartIndex]
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
                            <div ref={dropRef} className="LemonTextMarkdown flex flex-col gap-y-1 rounded relative">
                                <LemonTextArea
                                    ref={combinedRef}
                                    {...editAreaProps}
                                    autoFocus
                                    value={value}
                                    onKeyDown={(e) => {
                                        // Handle mentions keyboard navigation only when mentions are open
                                        if (mentionsOpen && filteredMembers.length > 0) {
                                            if (e.key === 'ArrowDown') {
                                                e.preventDefault()
                                                setSelectedMentionIndex((prev) =>
                                                    prev < filteredMembers.length - 1 ? prev + 1 : 0
                                                )
                                                return
                                            } else if (e.key === 'ArrowUp') {
                                                e.preventDefault()
                                                setSelectedMentionIndex((prev) =>
                                                    prev > 0 ? prev - 1 : filteredMembers.length - 1
                                                )
                                                return
                                            } else if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey) {
                                                e.preventDefault()
                                                selectMention(filteredMembers[selectedMentionIndex])
                                                return
                                            } else if (e.key === 'Escape') {
                                                e.preventDefault()
                                                setMentionsOpen(false)
                                                return
                                            }
                                        }

                                        // For all other cases, call the original handler
                                        editAreaProps.onKeyDown?.(e)
                                    }}
                                    onChange={(newValue) => {
                                        // Call the original onChange first
                                        onChange?.(newValue)

                                        // Also call editAreaProps.onChange if it exists and is different
                                        if (editAreaProps.onChange && editAreaProps.onChange !== onChange) {
                                            editAreaProps.onChange(newValue)
                                        }

                                        // Check for mentions after state update
                                        const textarea = textAreaRef.current
                                        if (textarea) {
                                            const cursorPosition = textarea.selectionStart
                                            const mention = detectMentions(newValue, cursorPosition)

                                            if (mention) {
                                                setMentionsQuery(mention.query)
                                                setMentionsStartIndex(mention.startIndex)

                                                // Get cursor position for popover
                                                const position = getCursorPosition(textarea, cursorPosition)
                                                setMentionsPosition(position)
                                                setMentionsOpen(true)
                                            } else {
                                                setMentionsOpen(false)
                                            }
                                        }
                                    }}
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
                                                <LemonButton
                                                    size="small"
                                                    icon={<IconImage className="text-lg" />}
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

                                {/* Mentions Popover */}
                                {mentionsOpen && (
                                    <div
                                        style={{
                                            position: 'absolute',
                                            top: mentionsPosition.top + 20,
                                            left: mentionsPosition.left,
                                            zIndex: 1000,
                                            backgroundColor: 'white',
                                            border: '1px solid #d1d5db',
                                            borderRadius: '6px',
                                            boxShadow:
                                                '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
                                            maxHeight: '200px',
                                            overflowY: 'auto',
                                            minWidth: '200px',
                                        }}
                                    >
                                        {filteredMembers.length > 0 ? (
                                            filteredMembers.map((member, index) => (
                                                <div
                                                    key={member.user.uuid}
                                                    className={`flex items-center gap-2 px-3 py-2 cursor-pointer ${
                                                        index === selectedMentionIndex
                                                            ? 'bg-blue-50'
                                                            : 'hover:bg-gray-50'
                                                    }`}
                                                    onClick={() => selectMention(member)}
                                                >
                                                    <ProfilePicture user={member.user} size="sm" />
                                                    <div className="flex-1 min-w-0">
                                                        <div className="text-sm font-medium text-gray-900 truncate">
                                                            {member.user.first_name} {member.user.last_name}
                                                        </div>
                                                        <div className="text-xs text-gray-500 truncate">
                                                            {member.user.email}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))
                                        ) : (
                                            <div className="px-3 py-2 text-sm text-gray-500">No members found</div>
                                        )}
                                    </div>
                                )}
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
