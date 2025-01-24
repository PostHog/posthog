import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { hasAnyInAppFrames, hasStacktrace } from 'scenes/error-tracking/utils'

import { ErrorTrackingIssueEventsPanel } from '../Events'

const Content = (): JSX.Element => {
    const { exceptionList } = useValues(errorTrackingIssueSceneLogic)
    const { showAllFrames } = useValues(stackFrameLogic)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return <ChainedStackTraces showAllFrames={hasAnyInApp ? showAllFrames : true} exceptionList={exceptionList} />
}

const EmptyState = (): JSX.Element => {
    return <div>No stacktrace</div>
}

const Header = ({ active }: { active: boolean }): JSX.Element => {
    const { exceptionList } = useValues(errorTrackingIssueSceneLogic)
    const { showAllFrames } = useValues(stackFrameLogic)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)
    const { setShowAllFrames } = useActions(stackFrameLogic)

    return (
        <div className="flex justify-between items-center w-full">
            <span>Stacktrace</span>
            {active && hasAnyInApp ? (
                <LemonSegmentedButton
                    onChange={(value, e) => {
                        e.stopPropagation()
                        setShowAllFrames(value === 'full')
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
    EmptyState,
    hasContent: ({ exceptionList }) => hasStacktrace(exceptionList),
} as ErrorTrackingIssueEventsPanel
