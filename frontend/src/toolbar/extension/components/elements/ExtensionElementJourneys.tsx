import { useActions, useValues } from 'kea'

import { ElementPathsSection } from '~/toolbar/shared/element-paths/ElementPathsSection'

import { extensionJourneysLogic } from '../../logics/panel/extensionJourneysLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'

/** Mounting this turns the paths on in the page, so `ExtensionInspectedElement` renders it only for a selected element. */
export function ExtensionElementJourneys(): JSX.Element | null {
    const { elementPathsView } = useValues(extensionJourneysLogic)
    const { reportSaveClicked, retryElementPaths } = useActions(extensionJourneysLogic)
    const { projectUrl } = useValues(extensionPanelLogic)

    return (
        <ElementPathsSection
            view={elementPathsView}
            heading={<div className="font-semibold">Journeys</div>}
            className="flex flex-col gap-1"
            appUrl={projectUrl}
            onSaveClick={reportSaveClicked}
            onRetry={retryElementPaths}
        />
    )
}
