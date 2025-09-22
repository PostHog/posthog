import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { IconComment, IconEmoji } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { cn } from 'lib/utils/css-classes'
import { playerCommentOverlayLogic } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function EmojiCommentRow({ onSelectEmoji }: { onSelectEmoji?: () => void }): JSX.Element {
    const {
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const theBuiltOverlayLogic = playerCommentOverlayLogic({ recordingId: sessionRecordingId, ...logicProps })
    const { addEmojiComment } = useActions(theBuiltOverlayLogic)

    const { favouriteEmojis } = useValues(emojiUsageLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)

    const onSelectedEmoji = useCallback((emoji: string) => {
        addEmojiComment(emoji)
        emojiUsed(emoji)
        onSelectEmoji?.()
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="flex flex-row items-center justify-around">
            {favouriteEmojis.map((emoji) => (
                <LemonButton key={emoji} onClick={() => onSelectedEmoji(emoji)} data-attr="emoji-quick-comment-button">
                    <span className="text-lg">{emoji}</span>
                </LemonButton>
            ))}
            <EmojiPickerPopover onSelect={onSelectedEmoji} data-attr="quick-comment-emoji-popover" />
        </div>
    )
}

export function CommentOnRecordingButton({ className }: { className?: string }): JSX.Element {
    const { setIsCommenting } = useActions(sessionRecordingPlayerLogic)
    const { isCommenting } = useValues(sessionRecordingPlayerLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.SessionRecording}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                size="xsmall"
                onClick={(e) => {
                    e.stopPropagation()
                    setIsCommenting(!isCommenting)
                }}
                tooltip={
                    isCommenting ? (
                        <>
                            Stop commenting <KeyboardShortcut c />
                        </>
                    ) : (
                        <>
                            Comment on this recording <KeyboardShortcut c />
                        </>
                    )
                }
                data-attr={isCommenting ? 'stop-annotating-recording' : 'annotate-recording'}
                active={isCommenting}
                icon={<IconComment className={cn('text-lg', className)} />}
            />
        </AccessControlAction>
    )
}

export function EmojiCommentOnRecordingButton({ className }: { className?: string }): JSX.Element {
    const { setQuickEmojiIsOpen } = useActions(sessionRecordingPlayerLogic)
    const { quickEmojiIsOpen } = useValues(sessionRecordingPlayerLogic)

    const {
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const theBuiltOverlayLogic = playerCommentOverlayLogic({ recordingId: sessionRecordingId, ...logicProps })
    const { isLoading } = useValues(theBuiltOverlayLogic)

    return (
        <LemonDropdown
            overlay={
                <EmojiCommentRow
                    onSelectEmoji={() => {
                        setQuickEmojiIsOpen(!quickEmojiIsOpen)
                    }}
                />
            }
            placement="bottom-end"
            visible={quickEmojiIsOpen}
            closeOnClickInside={false}
            onClickOutside={() => {
                setQuickEmojiIsOpen(!quickEmojiIsOpen)
            }}
            onVisibilityChange={(visible) => {
                setQuickEmojiIsOpen(visible)
            }}
        >
            <LemonButton
                size="xsmall"
                onClick={(e) => {
                    e.stopPropagation()
                    setQuickEmojiIsOpen(!quickEmojiIsOpen)
                }}
                tooltip={
                    quickEmojiIsOpen ? (
                        <>
                            Close emoji picker <KeyboardShortcut e />
                        </>
                    ) : (
                        <>
                            Emoji react at the current timestamp <KeyboardShortcut e />
                        </>
                    )
                }
                data-attr={quickEmojiIsOpen ? 'close-emoji-picker' : 'emoji-comment-dropdown'}
                active={quickEmojiIsOpen}
                disabledReason={isLoading ? 'Loading...' : undefined}
                icon={<IconEmoji className={cn('text-lg', className)} />}
            />
        </LemonDropdown>
    )
}
