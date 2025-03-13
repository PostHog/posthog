import './HedgehogBuddy.scss'

import { useActions } from 'kea'

import { hedgehogModeLogic } from './hedgehogModeLogic'

export function HedgehogMode(): JSX.Element | null {
    const { setGameElement } = useActions(hedgehogModeLogic)

    // useEffect(() => {
    //     if (!game) {
    //         return
    //     }

    //     // If party mode is enabled we are finding all the members that have hedgehog config and adding them to the game
    //     if (hedgehogConfig.party_mode_enabled) {
    //         const newHedgehogs: { [key: string]: { actor: any } } = {}

    //         members?.forEach((member) => {
    //             const memberHedgehogConfig: HedgehogConfig = {
    //                 ...hedgehogConfig,
    //                 // Reset some params to default
    //                 skin: 'default',
    //                 // Then apply the user's config
    //                 ...member.user.hedgehog_config,
    //                 // Finally some settings are forced
    //                 controls_enabled: false,
    //             }

    //             if (member.user.uuid !== user?.uuid && member.user.hedgehog_config) {
    //                 const player = game.spawnHedgehog(memberHedgehogConfig)
    //                 newHedgehogs[member.user.uuid] = { actor: player }
    //             }
    //         })
    //         setHedgehogs((prev) => ({ ...prev, ...newHedgehogs }))
    //     }
    // }, [game, hedgehogConfig.party_mode_enabled, members])

    // useEffect(() => ensureAllMembersLoaded(), [hedgehogConfig.enabled])

    // TODO: Wrap this component in error boundary as we dont want it to crash the app
    return (
        <div
            id="game"
            className="fixed inset-0 antialiased"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ zIndex: 99999 }}
            ref={(ref) => setGameElement(ref)}
        />
    )
}
