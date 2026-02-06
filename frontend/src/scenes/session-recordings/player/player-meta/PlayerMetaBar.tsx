import { PlayerMeta } from './PlayerMeta'
import { PlayerMetaTopSettings } from './PlayerMetaTopSettings'

export function PlayerMetaBar(): JSX.Element {
    return (
        <>
            <PlayerMeta />
            <PlayerMetaTopSettings />
        </>
    )
}
