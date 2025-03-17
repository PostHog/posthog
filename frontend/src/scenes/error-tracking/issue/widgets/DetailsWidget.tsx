import { LemonWidget } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getSessionId } from 'scenes/error-tracking/utils'

import { Overview } from '../Overview'

export function DetailsWidget(): JSX.Element {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const sessionId = getSessionId(issueProperties)
    return (
        <LemonWidget
            title="Details"
            actions={
                <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={issueProperties.timestamp}
                    inModal={true}
                    size="xsmall"
                    type="primary"
                    disabledReason={sessionId ? '' : 'No recording available'}
                />
            }
        >
            <div className="p-2">
                <Overview />
            </div>
        </LemonWidget>
    )
}
