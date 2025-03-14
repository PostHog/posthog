import { IconFilter, IconSort } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import { ErrorTrackingException } from 'lib/components/Errors/types'

import { errorTrackingIssueSceneLogic } from '../../errorTrackingIssueSceneLogic'
import { getExceptionAttributes, hasAnyInAppFrames } from '../../utils'
import { Widget } from './Widget'

export function StacktraceWidget(): JSX.Element {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)

    const { showAllFrames, frameOrderReversed } = useValues(stackFrameLogic)
    const { setShowAllFrames, reverseFrameOrder } = useActions(stackFrameLogic)
    const { exceptionList } = getExceptionAttributes(issueProperties)

    const hasAnyInApp = hasAnyInAppFrames(exceptionList)
    const orderedExceptions = applyFrameOrder(exceptionList, frameOrderReversed)

    return (
        <Widget.Root>
            <Widget.Header title="Stacktrace">
                <div className="flex gap-2">
                    <LemonButton
                        className="space-x-2"
                        type="tertiary"
                        size="xsmall"
                        onClick={() => reverseFrameOrder(!frameOrderReversed)}
                    >
                        <span className="me-1">{frameOrderReversed ? 'First call' : 'Last call'}</span>
                        <IconSort />
                    </LemonButton>
                    {hasAnyInApp && (
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
            </Widget.Header>
            <Widget.Body>
                <ChainedStackTraces
                    showAllFrames={hasAnyInApp ? showAllFrames : true}
                    exceptionList={orderedExceptions}
                />
            </Widget.Body>
        </Widget.Root>
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
