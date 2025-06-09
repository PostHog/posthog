import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { AnnotationScope } from '~/types'

import { playerCommentOverlayLogic } from './playerFrameCommentOverlayLogic'

const PlayerFrameCommentOverlayContent = (): JSX.Element | null => {
    const {
        isCommenting,
        sessionPlayerData: { sessionRecordingId },
        logicProps,
    } = useValues(sessionRecordingPlayerLogic)
    const { submitRecordingAnnotation } = useActions(
        playerCommentOverlayLogic({ recordingId: sessionRecordingId, ...logicProps })
    )

    return isCommenting ? (
        <div className="absolute bottom-4 left-4 z-20 w-60">
            <div className="flex flex-col bg-primary border border-border rounded p-2 shadow-lg">
                <Form
                    logic={playerCommentOverlayLogic}
                    formKey="recordingAnnotation"
                    id="recording-annotation-form"
                    enableFormOnSubmit
                    className="gap-y-2"
                >
                    <div className="flex flex-row gap-2">
                        <LemonField name="timeInRecording" label={<span>Comment at</span>} className="flex-1">
                            <LemonInput disabled={true} />
                        </LemonField>
                        <LemonField name="scope" label="Scope" className="flex-1">
                            <LemonSelect
                                options={[
                                    {
                                        value: AnnotationScope.Recording,
                                        label: 'Recording',
                                    },
                                    {
                                        value: AnnotationScope.Project,
                                        label: 'Project',
                                    },
                                    {
                                        value: AnnotationScope.Organization,
                                        label: 'Organization',
                                    },
                                ]}
                                fullWidth
                            />
                        </LemonField>
                    </div>
                    <LemonField name="content" label="Content">
                        <LemonTextArea
                            placeholder="Comment on this recording?"
                            data-attr="create-annotation-input"
                            maxLength={400}
                        />
                    </LemonField>
                    <div className="flex gap-2 mt-2 justify-end">
                        <LemonButton
                            form="recording-annotation-form"
                            type="primary"
                            onClick={submitRecordingAnnotation}
                            data-attr="create-recording-annotation-submit"
                            size="small"
                        >
                            Create
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
