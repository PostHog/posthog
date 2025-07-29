import { LemonButton, LemonInput, LemonTextAreaMarkdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { playerCommentOverlayLogic } from './playerFrameCommentOverlayLogic'

const PlayerFrameCommentOverlayContent = (): JSX.Element | null => {
    const {
        isCommenting,
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const { setIsCommenting } = useActions(sessionRecordingPlayerLogic)

    const playerCommentOverlayLogicProps = { recordingId: sessionRecordingId, ...logicProps }
    const theBuiltOverlayLogic = playerCommentOverlayLogic(playerCommentOverlayLogicProps)
    const { recordingComment, isRecordingCommentSubmitting } = useValues(theBuiltOverlayLogic)
    const { submitRecordingComment, resetRecordingComment } = useActions(theBuiltOverlayLogic)

    return isCommenting ? (
        <div className="absolute bottom-4 left-4 z-20 w-90">
            <div className="flex flex-col bg-primary border border-border rounded p-2 shadow-lg">
                <Form
                    logic={playerCommentOverlayLogic}
                    props={playerCommentOverlayLogicProps}
                    formKey="recordingComment"
                    id="recording-comment-form"
                    enableFormOnSubmit
                    className="flex flex-col gap-y-1"
                >
                    <div className="flex flex-col gap-y-1">
                        <LemonField name="commentId" className="hidden">
                            <input type="hidden" />
                        </LemonField>
                        <LemonField
                            name="timeInRecording"
                            label={<span>Comment at</span>}
                            inline={true}
                            className="justify-end"
                        >
                            <LemonInput disabled={true} />
                        </LemonField>
                    </div>
                    <div>
                        <LemonField name="content">
                            <LemonTextAreaMarkdown
                                placeholder="Comment on this recording?"
                                data-attr="create-recording-comment-input"
                                maxLength={400}
                            />
                        </LemonField>
                    </div>
                    <div className="flex gap-2 mt-2 justify-between">
                        <LemonButton
                            data-attr="cancel-recording-comment"
                            type="secondary"
                            onClick={() => {
                                resetRecordingComment()
                                setIsCommenting(false)
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="recording-comment-form"
                            type="primary"
                            onClick={submitRecordingComment}
                            data-attr="create-recording-comment-submit"
                            size="small"
                            loading={isRecordingCommentSubmitting}
                        >
                            {recordingComment.commentId ? 'Update' : 'Save'}
                        </LemonButton>
                    </div>
                </Form>
            </div>
        </div>
    ) : null
}

export function PlayerFrameCommentOverlay(): JSX.Element | null {
    const { isCommenting } = useValues(sessionRecordingPlayerLogic)
    return isCommenting ? <PlayerFrameCommentOverlayContent /> : null
}
