import { IconRecord } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

export function FeedbackRecordingAttachment(): JSX.Element {
    return (
        <div className="flex flex-row gap-2">
            <Tooltip title="Screen recording has been attached to help our support team understand your issue.">
                <LemonTag icon={<IconRecord />} type="success" size="medium">
                    screen_recording.mp4
                </LemonTag>
            </Tooltip>
        </div>
    )
}
