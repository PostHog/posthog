import { useValues } from 'kea'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getSessionId } from 'scenes/error-tracking/utils'

import { Overview } from '../Overview'
import { Widget } from './Widget'

export function DetailsWidget(): JSX.Element {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const sessionId = getSessionId(issueProperties)
    return (
        <Widget.Root>
            <Widget.Header title="Details">
                <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={issueProperties.timestamp}
                    inModal={true}
                    size="xsmall"
                    type="primary"
                    disabledReason={sessionId ? '' : 'No recording available'}
                />
            </Widget.Header>
            <Widget.Body>
                <Overview />
            </Widget.Body>
        </Widget.Root>
    )
}
