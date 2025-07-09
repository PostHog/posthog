import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { cn } from 'lib/utils/css-classes'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { playerCommentOverlayLogic } from './playerFrameCommentOverlayLogic'

const PlayerFrameCommentOverlayContent = (): JSX.Element | null => {
    const {
        isCommenting,
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const { setIsCommenting } = useActions(sessionRecordingPlayerLogic)

    const theBuiltOverlayLogic = playerCommentOverlayLogic({ recordingId: sessionRecordingId, ...logicProps })
    const { recordingAnnotation, isRecordingAnnotationSubmitting } = useValues(theBuiltOverlayLogic)
    const { submitRecordingAnnotation } = useActions(theBuiltOverlayLogic)

    return isCommenting ? (
        <div className="absolute bottom-4 left-4 z-20 w-60">
            <div className="flex flex-col bg-primary border border-border rounded p-2 shadow-lg">
                <Form
                    logic={playerCommentOverlayLogic}
                    formKey="recordingAnnotation"
                    id="recording-annotation-form"
                    enableFormOnSubmit
                    className="flex flex-col gap-y-1"
                >
                    <div className="flex flex-col gap-y-1">
                        <LemonField name="annotationId" className="hidden">
                            <input type="hidden" />
                        </LemonField>
                        <LemonField name="timeInRecording" label={<span>Comment at</span>} inline={true}>
                            <LemonInput disabled={true} />
                        </LemonField>
                    </div>
                    <div>
                        <LemonField name="content">
                            <LemonTextArea
                                placeholder="Comment on this recording?"
                                data-attr="create-annotation-input"
                                maxLength={400}
                            />
                        </LemonField>
                    </div>
                    <div
                        className={cn('flex flex-row gap-2 justify-end items-center text-text-3000 text-sm', {
                            'text-danger': (recordingAnnotation.content?.length ?? 0) > 400,
                        })}
                    >
                        {recordingAnnotation.content?.length ?? 0} / 400
                    </div>
                    <div className="flex gap-2 mt-2 justify-between">
                        <LemonButton
                            data-attr="cancel-recording-annotation"
                            type="secondary"
                            onClick={() => {
                                setIsCommenting(false)
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="recording-annotation-form"
                            type="primary"
                            onClick={submitRecordingAnnotation}
                            data-attr="create-recording-annotation-submit"
                            size="small"
                            loading={isRecordingAnnotationSubmitting}
                        >
                            {recordingAnnotation.annotationId ? 'Update' : 'Save'}
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
