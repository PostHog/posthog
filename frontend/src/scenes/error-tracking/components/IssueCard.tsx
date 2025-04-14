import { useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { RuntimeIcon } from './RuntimeIcon'

export function IssueCard(): JSX.Element {
    const { propertiesLoading, firstSeen, properties, sessionId } = useValues(errorTrackingIssueSceneLogic)
    return (
        <>
            <IssueHeader />
            <div className="flex justify-between items-center">
                {firstSeen && (
                    <div className="flex items-center space-x-1">
                        <span>First seen:</span>
                        <TZLabel className="text-muted text-xs" time={firstSeen} />
                    </div>
                )}
                {/* <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={properties.timestamp}
                    loading={propertiesLoading}
                    inModal={true}
                    size="xsmall"
                    type="secondary"
                    disabledReason={mightHaveRecording(properties) ? undefined : 'No recording available'}
                /> */}
            </div>
        </>
    )
}

function IssueHeader(): JSX.Element {
    const { issue, exceptionAttributes } = useValues(errorTrackingIssueSceneLogic)

    return (
        <div className="pb-1">
            <div className="flex gap-2 items-center h-7">
                {exceptionAttributes && <RuntimeIcon runtime={exceptionAttributes.runtime} />}
                <div className="font-bold text-lg">{issue?.name || 'Unknown'}</div>
                {/* TODO: add this back in */}
                {/* {part && <FingerprintRecordPartDisplay part={part} />} */}
            </div>
            <div className="text-tertiary leading-6">{issue?.description || 'Unknown'}</div>
        </div>
    )
}
