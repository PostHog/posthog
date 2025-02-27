import { LemonBanner, LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionAttributes, hasAnyInAppFrames } from 'scenes/error-tracking/utils'

import { ErrorTrackingIssueEventContent, ErrorTrackingIssueEventsPanel } from '../Events'

const Content = ({ hasStack, isThirdPartyScript }: ErrorTrackingIssueEventContent): JSX.Element | null => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const { showAllFrames } = useValues(stackFrameLogic)

    const { exceptionList } = getExceptionAttributes(issueProperties)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return hasStack ? (
        <ChainedStackTraces showAllFrames={hasAnyInApp ? showAllFrames : true} exceptionList={exceptionList} />
    ) : isThirdPartyScript ? (
        <LemonBanner type="error">
            <div className="space-y-2">
                <p>
                    It looks like this exception was thrown by a JavaScript file served from a different origin to your
                    site. This is most likely from a third party script running on your site. Loading scripts
                    anonymously will add stack traces to thrown exceptions.
                </p>
                <div className="flex">
                    <LemonButton
                        type="primary"
                        status="danger"
                        to="https://posthog.com/docs/error-tracking/common-questions#what-is-a-script-error-with-no-stack-traces"
                    >
                        Learn more
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    ) : null
}

const Header = ({
    active,
    hasStack,
    isThirdPartyScript,
}: { active: boolean } & ErrorTrackingIssueEventContent): JSX.Element | null => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const { showAllFrames } = useValues(stackFrameLogic)
    const { setShowAllFrames } = useActions(stackFrameLogic)

    const { exceptionList } = getExceptionAttributes(issueProperties)
    const hasAnyInApp = hasAnyInAppFrames(exceptionList)

    return (
        <div className="flex justify-between items-center w-full">
            <span>Stack trace</span>
            {active && hasAnyInApp && (hasStack || !isThirdPartyScript) ? (
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
    hasContent: ({ hasStack, isThirdPartyScript }) => hasStack || isThirdPartyScript,
} as ErrorTrackingIssueEventsPanel
