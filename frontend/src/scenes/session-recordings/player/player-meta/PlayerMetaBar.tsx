import { PlayerMeta } from './PlayerMeta'
import { useReportLowTtlViewed } from './PlayerMetaTopSettings'

export function PlayerMetaBar(): JSX.Element {
    useReportLowTtlViewed()

    return <PlayerMeta />
}
