import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionAttributes, hasAnyInAppFrames } from 'scenes/error-tracking/utils'

import { ErrorTrackingIssueEventsPanel } from '../Events'

const Content = (): JSX.Element => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const { showAllFrames } = useValues(stackFrameLogic)

    const { exceptionList } = getExceptionAttributes(issueProperties)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return <ChainedStackTraces showAllFrames={hasAnyInApp ? showAllFrames : true} exceptionList={exceptionList} />
}

const Header = ({ active }: { active: boolean }): JSX.Element => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const { showAllFrames } = useValues(stackFrameLogic)
    const { setShowAllFrames } = useActions(stackFrameLogic)

    const { exceptionList } = getExceptionAttributes(issueProperties)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return (
        <div className="flex justify-between items-center w-full">
            <span>Stack trace</span>
            {active && hasAnyInApp ? (
                <LemonSegmentedButton
                    onChange={(value, e) => {
                        setShowAllFrames(value === 'full')
                        e.stopPropagation()
                    }}
                    value={showAllFrames ? 'full' : 'in-app'}
                    options={[
                        {
                            value: 'in-app',
                            label: 'In app only',
                        },
                        {
                            value: 'full',
                            label: 'Show full stack',
                        },
                    ]}
                    size="xsmall"
                />
            ) : null}
        </div>
    )
}

export default {
    key: 'stacktrace',
    Content,
    Header,
    hasContent: ({ hasStack }) => hasStack,
} as ErrorTrackingIssueEventsPanel
