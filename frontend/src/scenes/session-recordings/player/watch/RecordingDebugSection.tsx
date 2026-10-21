import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { NetworkView } from 'scenes/session-recordings/apm/NetworkView'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'

import { SessionRecordingSidebarTab } from '~/types'

const DEBUG_TABS = [SessionRecordingSidebarTab.INSPECTOR, SessionRecordingSidebarTab.NETWORK_WATERFALL]

/** Events, console and network under the summary, shown in Debug mode only. */
export function RecordingDebugSection(): JSX.Element {
    const { activeTab } = useValues(playerSidebarLogic)
    const { setTab } = useActions(playerSidebarLogic)
    // The sidebar logic still receives tabs this section does not own, such as Observations; they land on the inspector.
    const tab = DEBUG_TABS.includes(activeTab) ? activeTab : SessionRecordingSidebarTab.INSPECTOR

    return (
        <div className="flex flex-col border rounded bg-surface-primary overflow-hidden" data-attr="watch-panel-debug">
            <LemonTabs
                size="small"
                activeKey={tab}
                onChange={(next) => setTab(next)}
                barClassName="!mb-0 px-2"
                tabs={[
                    {
                        key: SessionRecordingSidebarTab.INSPECTOR,
                        label: 'Inspector',
                        'data-attr': 'watch-panel-debug-inspector',
                    },
                    {
                        key: SessionRecordingSidebarTab.NETWORK_WATERFALL,
                        label: 'Network waterfall',
                        'data-attr': 'watch-panel-debug-network',
                    },
                ]}
            />
            <div className="flex flex-col h-[60vh] min-h-96 overflow-hidden">
                {tab === SessionRecordingSidebarTab.NETWORK_WATERFALL ? <NetworkView /> : <PlayerInspector />}
            </div>
        </div>
    )
}
