import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import {
    playerCommentOverlayLogic,
    quickEmojis,
} from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { IconComment } from 'lib/lemon-ui/icons'

export function EmojiCommentRow({ onSelectEmoji }: { onSelectEmoji?: () => void }): JSX.Element {
    const {
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const theBuiltOverlayLogic = playerCommentOverlayLogic({ recordingId: sessionRecordingId, ...logicProps })
    const { addEmojiComment } = useActions(theBuiltOverlayLogic)

    return (
        <div className="flex flex-row items-center justify-around">
            {quickEmojis.map((emoji) => (
                <LemonButton
                    key={emoji}
                    onClick={() => {
                        addEmojiComment(emoji)
                        onSelectEmoji?.()
                    }}
                    data-attr="emoji-quick-comment-button"
                >
                    {emoji}
                </LemonButton>
            ))}
        </div>
    )
}

export function CommentOnRecordingButton(): JSX.Element {
    const { setIsCommenting } = useActions(sessionRecordingPlayerLogic)
    const { isCommenting } = useValues(sessionRecordingPlayerLogic)

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
            icon={<IconComment className="text-xl" />}
            sideAction={{
                dropdown: {
                    placement: 'bottom-end',
                    overlay: <EmojiCommentRow />,
                },
                'data-attr': 'emoji-comment-dropdown',
            }}
        >
            Comment
        </LemonButton>
    )
}
