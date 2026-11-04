import { useActions, useValues } from 'kea'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@posthog/quill'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { RecordingOverviewPanels } from './RecordingOverviewPanels'

export function RecordingOverviewDisclosure(): JSX.Element {
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)

    return (
        <Collapsible
            data-quill
            open={watchPanelOpenSections.includes('overview')}
            onOpenChange={() => toggleWatchPanelSection('overview')}
            data-attr="watch-panel-section-overview"
        >
            <CollapsibleTrigger className="w-full">
                Overview
                <span className="grow" />
            </CollapsibleTrigger>
            <CollapsibleContent>
                <RecordingOverviewPanels />
            </CollapsibleContent>
        </Collapsible>
    )
}
