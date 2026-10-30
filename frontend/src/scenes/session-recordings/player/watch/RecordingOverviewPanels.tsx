import { useValues } from 'kea'
import { ReactNode } from 'react'

import { SettingsSnapshot } from 'lib/components/SettingsSnapshot'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { TTLWarning } from 'scenes/session-recordings/player/player-meta/PlayerMetaTopSettings'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { OVERVIEW_SNAPSHOT_SCOPE } from 'scenes/session-recordings/player/sidebar/overviewSnapshotScope'
import { PlayerSidebarExperimentsSection } from 'scenes/session-recordings/player/sidebar/PlayerSidebarExperimentsSection'
import { PlayerSidebarOverviewDeviceTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewDeviceTab'
import { PlayerSidebarOverviewOtherWatchers } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewOtherWatchers'
import { PlayerSidebarOverviewPersonTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewPersonTab'
import { PlayerSidebarOverviewSessionTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewSessionTab'
import { PlayerSidebarOverviewTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewTab'

const WIDE_OVERVIEW_PX = 960

export function RecordingOverviewPanels(): JSX.Element {
    const { ref, size } = useResizeBreakpoints({ 0: 'narrow', [WIDE_OVERVIEW_PX]: 'wide' })

    return (
        <div ref={ref} data-attr="watch-panel-overview">
            {size === 'wide' ? <WideOverview /> : <PlayerSidebarOverviewTab />}
        </div>
    )
}

function WideOverview(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { snapshotAt } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col gap-2 bg-primary px-2 py-2">
            <TTLWarning />
            <div className="grid grid-cols-3 gap-x-2 gap-y-1">
                <OverviewColumn title="Session" dataAttr="watch-overview-session">
                    <PlayerSidebarOverviewSessionTab />
                </OverviewColumn>
                <OverviewColumn title="Person" dataAttr="watch-overview-person">
                    <PlayerSidebarOverviewPersonTab />
                </OverviewColumn>
                <OverviewColumn title="Device" dataAttr="watch-overview-device">
                    <PlayerSidebarOverviewDeviceTab />
                </OverviewColumn>
            </div>
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'replay-settings',
                        header: 'Settings at the time of the recording',
                        content: (
                            <SettingsSnapshot at={snapshotAt} scope={OVERVIEW_SNAPSHOT_SCOPE} title="" layout="grid" />
                        ),
                    },
                ]}
            />
            <PlayerSidebarExperimentsSection />
            <PlayerSidebarOverviewOtherWatchers />
        </div>
    )
}

function OverviewColumn({
    title,
    dataAttr,
    children,
}: {
    title: string
    dataAttr: string
    children: ReactNode
}): JSX.Element {
    // subgrid keeps the headings, top cards and row tables level across columns
    return (
        <div className="grid grid-cols-1 grid-rows-subgrid row-span-3 gap-1 min-w-0" data-attr={dataAttr}>
            <span className="text-xxs font-semibold uppercase tracking-wide text-secondary px-0.5">{title}</span>
            {children}
        </div>
    )
}
