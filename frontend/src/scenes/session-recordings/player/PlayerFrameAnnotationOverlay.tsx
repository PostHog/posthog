import { useValues, useActions } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { AnnotationScope } from '~/types'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { playerAnnotationOverlayLogic } from './playerFrameAnnotationOverlayLogic'

const PlayerFrameAnnotationOverlayContent = (): JSX.Element | null => {
    const { isAnnotating, sessionPlayerData: { durationMs, sessionRecordingId }, logicProps, currentPlayerTime } = useValues(sessionRecordingPlayerLogic)
    const { submitRecordingAnnotation } = useActions(playerAnnotationOverlayLogic({ recordingId: sessionRecordingId, ...logicProps }))

    return isAnnotating ? (
        <div className="absolute bottom-4 left-4 z-20 w-200">
            <div className="flex flex-col bg-primary border border-border rounded p-2 shadow-lg">
                <Form
                    logic={playerAnnotationOverlayLogic}
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
                        <LemonButton form="recording-annotation-form" type="primary" onClick={submitRecordingAnnotation} data-attr="create-recording-annotation-submit" size="small">
                            Create
                        </LemonButton>
                    </div>
                </Form>
            </div>
        </div>
    ) : null
}

export function PlayerFrameAnnotationOverlay(): JSX.Element {
    const { isAnnotating } = useValues(sessionRecordingPlayerLogic)
    return (
        <div className="absolute inset-0 z-11">
            {isAnnotating ? <PlayerFrameAnnotationOverlayContent /> : null}
        </div>
    )
}
