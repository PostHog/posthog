import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import PanelLayout from 'lib/components/PanelLayout/PanelLayout'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionProperties, hasStacktrace } from 'scenes/error-tracking/utils'

import { MetaPanel } from '../panels/MetaPanel'

export const OverviewTab = (): JSX.Element => {
    const { showAllFrames } = useValues(stackFrameLogic)
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)
    const { setShowAllFrames } = useActions(stackFrameLogic)

    const { exceptionList } = getExceptionProperties(issueProperties)
    const exceptionWithStack = hasStacktrace(exceptionList)

    return (
        <PanelLayout className="ErrorTrackingPanelLayout">
            <PanelLayout.Container primary column>
                {/* <PanelLayout.Panel primary={false}>
                    <PanelLayout.PanelHeader title="Overview">
                        <PanelLayout.SettingsButton
                            label={`Show ${showLatestException ? 'earliest' : 'latest'} issue`}
                            onClick={() => setShowLatestException(!showLatestException)}
                        />
                    </PanelLayout.PanelHeader>
                    <OverviewPanel />
                </PanelLayout.Panel> */}
                {exceptionWithStack && (
                    <PanelLayout.Panel primary={false} className="space-y-2">
                        <PanelLayout.PanelHeader title="Stacktrace">
                            <PanelLayout.SettingsToggle
                                active={showAllFrames}
                                label="Show entire trace"
                                onClick={() => setShowAllFrames(!showAllFrames)}
                            />
                        </PanelLayout.PanelHeader>
                        <div className="space-y-6">
                            <ChainedStackTraces embedded showAllFrames={showAllFrames} exceptionList={exceptionList} />
                        </div>
                    </PanelLayout.Panel>
                )}
                {/* <PanelLayout.Panel primary={false} title='Recording'>Recording</PanelLayout.Panel> */}
            </PanelLayout.Container>
            <PanelLayout.Container column primary={false} className="h-full">
                <PanelLayout.Panel primary={false}>
                    <PanelLayout.PanelHeader title="Meta" />
                    <MetaPanel />
                </PanelLayout.Panel>
            </PanelLayout.Container>
        </PanelLayout>
    )
}
