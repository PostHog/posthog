import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { playerCommentOverlayLogic } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { IconEmoji, IconComment } from '@posthog/icons'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { useCallback, useState } from 'react'
import { Spinner } from 'lib/lemon-ui/Spinner'

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
    }, [])

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

export function CommentOnRecordingButton(): JSX.Element {
    const { setIsCommenting } = useActions(sessionRecordingPlayerLogic)
    const { isCommenting } = useValues(sessionRecordingPlayerLogic)

    const [quickEmojiIsOpen, setQuickEmojiIsOpen] = useState<boolean>(false)

    const {
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const theBuiltOverlayLogic = playerCommentOverlayLogic({ recordingId: sessionRecordingId, ...logicProps })
    const { isLoading } = useValues(theBuiltOverlayLogic)

    return (
        <LemonButton
            size="xsmall"
            onClick={() => setIsCommenting(!isCommenting)}
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
            icon={<IconComment className="text-lg" />}
            sideAction={{
                icon: isLoading ? <Spinner textColored={true} /> : <IconEmoji className="text-lg" />,
                onClick: () => {
                    if (isLoading) {
                        return
                    }
                    setQuickEmojiIsOpen(!quickEmojiIsOpen)
                },
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <EmojiCommentRow
                            onSelectEmoji={() => {
                                setQuickEmojiIsOpen(!quickEmojiIsOpen)
                            }}
                        />
                    ),
                    // because of the emoji picker popover
                    // we have to manually manage when the overlay closes
                    visible: quickEmojiIsOpen,
                    closeOnClickInside: false,
                    onClickOutside: () => {
                        setQuickEmojiIsOpen(!quickEmojiIsOpen)
                    },
                },
                'data-attr': 'emoji-comment-dropdown',
            }}
        >
            Comment
        </LemonButton>
    )
}
