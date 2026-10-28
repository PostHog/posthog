import { useValues } from 'kea'

import { playerUsesWatchLayout } from 'scenes/session-recordings/playlist/replayLayout'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerModeBar } from '../watch/PlayerModeBar'
import { PlayerMeta } from './PlayerMeta'
import { useReportLowTtlViewed } from './PlayerMetaTopSettings'

export function PlayerMetaBar(): JSX.Element {
    useReportLowTtlViewed()
    const { replayLayout } = useValues(playerSettingsLogic)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)

    return playerUsesWatchLayout(replayLayout, logicProps) ? <PlayerModeBar /> : <PlayerMeta />
}
