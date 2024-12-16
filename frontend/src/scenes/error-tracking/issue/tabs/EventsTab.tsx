import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import PanelLayout from 'lib/components/PanelLayout/PanelLayout'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'

import { OverviewPanel } from '../panels/OverviewPanel'
import { PlaylistPanel } from '../panels/PlaylistPanel'

export const EventsTab = (): JSX.Element => {
    const { activeEvent } = useValues(errorTrackingIssueSceneLogic)

    return (
        <PanelLayout className="ErrorTrackingPanelLayout">
            <PanelLayout.Container primary column className="flex-col h-full overflow-y-auto">
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
                <PanelLayout.Panel primary title="Events" className="flex flex-col overflow-y-auto">
                    <PlaylistPanel />
                </PanelLayout.Panel>
            </PanelLayout.Container>
        </PanelLayout>
    )
}
