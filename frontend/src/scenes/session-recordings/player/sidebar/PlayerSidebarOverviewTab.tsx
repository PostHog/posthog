import { useActions, useValues } from 'kea'

import { SettingsSnapshot } from 'lib/components/SettingsSnapshot'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { OverviewTab } from '../player-meta/overviewTabs'
import { playerMetaLogic } from '../player-meta/playerMetaLogic'
import { TTLWarning } from '../player-meta/PlayerMetaTopSettings'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarExperimentsSection } from './PlayerSidebarExperimentsSection'
import { playerSidebarLogic } from './playerSidebarLogic'
import { PlayerSidebarOverviewDeviceTab } from './PlayerSidebarOverviewDeviceTab'
import { PlayerSidebarOverviewOtherWatchers } from './PlayerSidebarOverviewOtherWatchers'
import { PlayerSidebarOverviewPersonTab } from './PlayerSidebarOverviewPersonTab'
import { PlayerSidebarOverviewSessionTab } from './PlayerSidebarOverviewSessionTab'

const SNAPSHOT_SCOPE: string[] = [
    'session_recording_opt_in',
    'session_recording_sample_rate',
    'session_recording_minimum_duration_milliseconds',
    'session_recording_linked_flag',
    'session_recording_network_payload_capture_config',
    'session_recording_masking_config',
    'session_recording_url_trigger_config',
    'session_recording_url_blocklist_config',
    'session_recording_event_trigger_config',
    'session_recording_retention_period',
    'session_recording_trigger_match_type_config',
    'session_recording_trigger_groups',
    'session_replay_config',
    'recording_domains',
]

const OVERVIEW_TAB_OPTIONS: { value: OverviewTab; label: string; 'data-attr': string }[] = [
    { value: 'session', label: 'Session', 'data-attr': 'replay-overview-tab-session' },
    { value: 'person', label: 'Person', 'data-attr': 'replay-overview-tab-person' },
    { value: 'device', label: 'Device', 'data-attr': 'replay-overview-tab-device' },
]

export function ResolutionView(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)

    const { resolutionDisplay, scaleDisplay, loading } = useValues(playerMetaLogic(logicProps))

    return loading ? (
        <LemonSkeleton className="w-1/3 h-4" />
    ) : (
        <Tooltip
            placement="bottom"
            title={
                <>
                    The resolution of the page as it was captured was <b>{resolutionDisplay}</b>
                    <br />
                    You are viewing the replay at <b>{scaleDisplay}</b> of the original size
                </>
            }
        >
            <span className="text-secondary text-xs flex flex-row items-center gap-x-1 tabular-nums">
                <span>{resolutionDisplay}</span>
                <span>({scaleDisplay})</span>
            </span>
        </Tooltip>
    )
}

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson, snapshotAt } = useValues(playerMetaLogic(logicProps))
    const { overviewTab } = useValues(playerSidebarLogic)
    const { setOverviewTab } = useActions(playerSidebarLogic)
    const consolidatedControls = useFeatureFlag('REPLAY_CONSOLIDATED_CONTROLS')

    return (
        <div className="flex flex-col overflow-auto bg-primary px-2 py-1 h-full gap-1">
            <div className="flex flex-row justify-between items-center gap-2 min-w-0">
                <div className="min-w-0 flex-1">
                    <PersonDisplay person={sessionPerson} withIcon withCopyButton placement="bottom" />
                </div>
                <ResolutionView />
            </div>
            {consolidatedControls && <TTLWarning variant="inline" />}
            <LemonSegmentedButton
                value={overviewTab}
                onChange={(tab) => setOverviewTab(tab)}
                options={OVERVIEW_TAB_OPTIONS}
                size="small"
                fullWidth
            />
            {overviewTab === 'person' ? (
                <PlayerSidebarOverviewPersonTab />
            ) : overviewTab === 'device' ? (
                <PlayerSidebarOverviewDeviceTab />
            ) : (
                <PlayerSidebarOverviewSessionTab />
            )}
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'replay-settings',
                        header: 'Settings at the time of the recording',
                        content: <SettingsSnapshot at={snapshotAt} scope={SNAPSHOT_SCOPE} title="" />,
                    },
                ]}
            />
            <PlayerSidebarExperimentsSection />
            <PlayerSidebarOverviewOtherWatchers />
        </div>
    )
}
