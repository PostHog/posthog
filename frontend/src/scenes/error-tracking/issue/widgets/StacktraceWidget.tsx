import { IconFilter, IconSort } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonWidget } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import { ErrorTrackingException } from 'lib/components/Errors/types'

import { errorTrackingIssueSceneLogic } from '../../errorTrackingIssueSceneLogic'
import { getExceptionAttributes, hasAnyInAppFrames, hasStacktrace } from '../../utils'

export function StacktraceWidget(): JSX.Element {
    const { properties, propertiesLoading } = useValues(errorTrackingIssueSceneLogic)

    const { showAllFrames, frameOrderReversed } = useValues(stackFrameLogic)
    const { setShowAllFrames, reverseFrameOrder } = useActions(stackFrameLogic)
    const { exceptionList } = getExceptionAttributes(properties)

    const showStacktrace = hasStacktrace(exceptionList)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)
    const orderedExceptions = applyFrameOrder(exceptionList, frameOrderReversed)

    return (
        <LemonWidget
            title="Stacktrace"
            actions={
                <div className="flex gap-2">
                    {!propertiesLoading && showStacktrace && (
                        <LemonButton
                            className="space-x-2"
                            type="tertiary"
                            size="xsmall"
                            onClick={() => reverseFrameOrder(!frameOrderReversed)}
                        >
                            <span className="me-1">{frameOrderReversed ? 'First call' : 'Last call'}</span>
                            <IconSort />
                        </LemonButton>
                    )}
                    {!propertiesLoading && hasAnyInApp && (
                        <LemonButton
                            className="space-x-2"
                            type="tertiary"
                            size="xsmall"
                            onClick={() => setShowAllFrames(!showAllFrames)}
                        >
                            <span className="me-1">{showAllFrames ? 'Full stack' : 'In app'}</span>
                            <IconFilter />
                        </LemonButton>
                    )}
                </div>
            }
        >
            <div className="p-2">
                {!propertiesLoading && showStacktrace && (
                    <ChainedStackTraces
                        showAllFrames={hasAnyInApp ? showAllFrames : true}
                        exceptionList={orderedExceptions}
                    />
                )}
                {!propertiesLoading && !showStacktrace && (
                    <EmptyMessage
                        title="No stacktrace available"
                        description="Make sure sdk is setup correctly or contact support if problem persists"
                        buttonText="Check documentation"
                        buttonTo="https://posthog.com/docs/error-tracking/installation"
                    />
                )}
                {propertiesLoading && (
                    <div className="space-y-2">
                        <LemonSkeleton />
                        <LemonSkeleton.Row repeat={2} />
                    </div>
                )}
            </div>
        </LemonWidget>
    )
}

function applyFrameOrder(
    exceptionList: ErrorTrackingException[],
    frameOrderReversed: boolean
): ErrorTrackingException[] {
    if (frameOrderReversed) {
        exceptionList = exceptionList
            .map((exception) => {
                if (exception.stacktrace) {
                    exception.stacktrace.frames = exception.stacktrace.frames.slice().reverse()
                }
                return exception
            })
            .reverse()
    }
    return exceptionList
}
