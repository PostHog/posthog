import { LemonWidget } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getSessionId } from 'scenes/error-tracking/utils'

import { Overview } from '../Overview'

export function DetailsWidget(): JSX.Element {
    const { properties } = useValues(errorTrackingIssueSceneLogic)
    const sessionId = getSessionId(properties)
    return (
        <LemonWidget
            title="Details"
            actions={
                <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={properties.timestamp}
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
