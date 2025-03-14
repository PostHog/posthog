import { useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { getExceptionAttributes, hasAnyInAppFrames } from '../utils'

export type ErrorTrackingIssueEventContent = {
    hasStack: boolean
    hasRecording: boolean
    isThirdPartyScript: boolean
}

export type ErrorTrackingIssueEventsPanel = {
    key: 'stacktrace' | 'recording'
    Content: (props: ErrorTrackingIssueEventContent) => JSX.Element | null
    Header: string | (({ active }: { active: boolean } & ErrorTrackingIssueEventContent) => JSX.Element | null)
    hasContent: (props: ErrorTrackingIssueEventContent) => boolean
    className?: string
}

export const Stacktrace = (): JSX.Element => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)

    const { showAllFrames } = useValues(stackFrameLogic)

    const { exceptionList } = getExceptionAttributes(issueProperties)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return <ChainedStackTraces showAllFrames={hasAnyInApp ? showAllFrames : true} exceptionList={exceptionList} />
}
