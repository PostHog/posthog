import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import PanelLayout from 'lib/components/PanelLayout/PanelLayout'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

import { MetaPanel } from '../panels/MetaPanel'
import { OverviewPanel } from '../panels/OverviewPanel'

export const OverviewTab = (): JSX.Element => {
    const { activeEvent } = useValues(errorTrackingIssueSceneLogic)

    return (
        <PanelLayout className="ErrorTrackingPanelLayout">
            <PanelLayout.Container primary column>
                <PanelLayout.Panel title="Overview" primary={false}>
                    <OverviewPanel />
                </PanelLayout.Panel>
                {activeEvent && (
                    <PanelLayout.Panel primary={false} title="Stacktrace">
                        <ErrorDisplay eventProperties={activeEvent.properties} />
                    </PanelLayout.Panel>
                )}
                {/* <PanelLayout.Panel primary={false} title='Recording'>Recording</PanelLayout.Panel> */}
            </PanelLayout.Container>
            <PanelLayout.Container column primary={false} className="h-full">
                <PanelLayout.Panel primary={false} title="Meta">
                    <MetaPanel />
                </PanelLayout.Panel>
            </PanelLayout.Container>
        </PanelLayout>
    )
}
