import { useActions, useValues } from 'kea'

import { elementPathsLogic } from '~/toolbar/shared/element-paths/elementPathsLogic'
import { ElementPathsSection } from '~/toolbar/shared/element-paths/ElementPathsSection'
import { toolbarAppUrl } from '~/toolbar/shared/toolbarConfigLogic'

/** Mounting this mounts `elementPathsLogic`, so `ElementInfo` renders it only for a selected element. */
export function ElementInfoJourneys(): JSX.Element | null {
    const { elementPathsView } = useValues(elementPathsLogic)
    const { reportSaveClicked, retryElementPaths } = useActions(elementPathsLogic)

    return (
        <ElementPathsSection
            view={elementPathsView}
            heading={<h1 className="section-title">Journeys</h1>}
            className="p-3 border-l-[5px] border-l-accent bg-surface-primary text-primary"
            appUrl={toolbarAppUrl}
            onSaveClick={reportSaveClicked}
            onRetry={retryElementPaths}
        />
    )
}
