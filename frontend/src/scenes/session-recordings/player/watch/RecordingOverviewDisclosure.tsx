import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { RecordingOverviewPanels } from './RecordingOverviewPanels'

/** The sidebar's Overview behind a disclosure, remembered across recordings. */
export function RecordingOverviewDisclosure(): JSX.Element {
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)
    const open = watchPanelOpenSections.includes('overview')

    return (
        <div className="flex flex-col gap-2">
            <LemonButton
                size="xsmall"
                sideIcon={open ? <IconChevronDown /> : <IconChevronRight />}
                active={open}
                onClick={() => toggleWatchPanelSection('overview')}
                className="self-start"
                data-attr="watch-panel-section-overview"
            >
                Overview
            </LemonButton>
            {open && (
                <div className="border rounded overflow-hidden">
                    <RecordingOverviewPanels />
                </div>
            )}
        </div>
    )
}
