import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { PlayerMeta } from './PlayerMeta'
import { PlayerMetaTopSettings, useReportLowTtlViewed } from './PlayerMetaTopSettings'

export function PlayerMetaBar(): JSX.Element {
    const consolidatedControls = useFeatureFlag('REPLAY_CONSOLIDATED_CONTROLS')
    useReportLowTtlViewed()

    if (consolidatedControls) {
        return <PlayerMeta consolidated />
    }

    return (
        <>
            <PlayerMeta />
            <PlayerMetaTopSettings />
        </>
    )
}
