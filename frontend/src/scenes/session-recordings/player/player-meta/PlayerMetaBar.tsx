import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { PlayerMeta } from './PlayerMeta'
import { PlayerMetaTopSettings } from './PlayerMetaTopSettings'

export function PlayerMetaBar(): JSX.Element {
    const consolidatedControls = useFeatureFlag('REPLAY_CONSOLIDATED_CONTROLS')

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
