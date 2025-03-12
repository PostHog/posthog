import './HedgehogBuddy.scss'

import { useActions } from 'kea'

import { hedgehogModeLogic } from './hedgehogModeLogic'

export function HedgehogMode(): JSX.Element {
    const { setGameRef } = useActions(hedgehogModeLogic)

    // useEffect(() => {
    //     if (ref) {
    //         const hedgeHogMode = new HedgeHogMode({
    //             assetsUrl: '/static/hedgehog-mode/',
    //             platformSelector:
    //                 '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable, .LemonSwitch--bordered',
    //         })
    //         hedgeHogMode
    //             .render(ref)
    //             .then(() => {
    //                 setGame(hedgeHogMode)
    //             })
    //             .catch((e) => {
    //                 console.error('Error rendering hedgehog mode', e)
    //             })
    //     }
    //     return () => game?.destroy()
    // }, [ref])

    // useEffect(() => {
    //     if (!game) {
    //         return
    //     }
    //     const player = hedgehogs['me']?.actor ?? game.spawnHedgehog(hedgehogConfig)
    //     game.isDebugging = true

    //     player.updateOptions(hedgehogConfig)

    //     setHedgehogs((prev) => ({ ...prev, ['me']: { actor: player } }))
    // }, [game, hedgehogConfig])

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
    return <div id="game" className="fixed inset-0 antialiased" style={{ zIndex: 99999 }} ref={setGameRef} />
}
