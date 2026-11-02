import { useActions, useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { RecordingOverviewPanels } from './RecordingOverviewPanels'

export function RecordingOverviewDisclosure(): JSX.Element {
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)
    const open = watchPanelOpenSections.includes('overview')

    return (
        <LemonCollapse
            size="small"
            panels={[
                {
                    key: 'overview',
                    header: 'Overview',
                    content: <RecordingOverviewPanels />,
                    dataAttr: 'watch-panel-section-overview',
                },
            ]}
            activeKey={open ? 'overview' : null}
            onChange={() => toggleWatchPanelSection('overview')}
        />
    )
}
