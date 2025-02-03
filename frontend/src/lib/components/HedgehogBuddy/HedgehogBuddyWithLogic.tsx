import './HedgehogBuddy.scss'

import { HedgeHogMode } from '@posthog/hedgehog-mode'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { HedgehogConfig } from '~/types'

import { MemberHedgehogBuddy, MyHedgehogBuddy } from './HedgehogBuddy'
import { hedgehogBuddyLogic } from './hedgehogBuddyLogic'

export function HedgehogBuddyWithLogic(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { patchHedgehogConfig } = useActions(hedgehogBuddyLogic)
    const { user } = useValues(userLogic)
    const { members } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const [ref, setRef] = useState<HTMLDivElement | null>(null)
    const [game, setGame] = useState<HedgeHogMode | null>(null)

    const [hedgehogs, setHedgehogs] = useState<{
        [key: string]: {
            actor: ReturnType<HedgeHogMode['spawnHedgehog']>
        }
    }>({})

    useEffect(() => {
        if (ref) {
            const hedgeHogMode = new HedgeHogMode({
                assetsUrl: '/static/hedgehog-mode/',
                platformSelector:
                    '.border, .border-t, .LemonButton--primary, .LemonButton--secondary:not(.LemonButton--status-alt:not(.LemonButton--active)), .LemonInput, .LemonSelect, .LemonTable',
            })
            hedgeHogMode
                .render(ref)
                .then(() => {
                    setGame(hedgeHogMode)
                })
                .catch((e) => {
                    console.error('Error rendering hedgehog mode', e)
                })
        }
    }, [ref])

    useEffect(() => {
        if (!game) {
            return
        }
        const player = hedgehogs['me']?.actor ?? game.spawnHedgehog(hedgehogConfig)
        game.isDebugging = true

        player.updateOptions(hedgehogConfig)

        setHedgehogs((prev) => ({ ...prev, ['me']: { actor: player } }))
    }, [game, hedgehogConfig])

    useEffect(() => {
        if (!game) {
            return
        }

        // If party mode is enabled we are finding all the members that have hedgehog config and adding them to the game
        if (hedgehogConfig.party_mode_enabled) {
            const newHedgehogs: { [key: string]: { actor: any } } = {}

            members?.forEach((member) => {
                const memberHedgehogConfig: HedgehogConfig = {
                    ...hedgehogConfig,
                    // Reset some params to default
                    skin: 'default',
                    // Then apply the user's config
                    ...member.user.hedgehog_config,
                    // Finally some settings are forced
                    controls_enabled: false,
                }

                if (member.user.uuid !== user?.uuid && member.user.hedgehog_config) {
                    const player = game.spawnHedgehog(memberHedgehogConfig)
                    newHedgehogs[member.user.uuid] = { actor: player }
                }
            })
            setHedgehogs((prev) => ({ ...prev, ...newHedgehogs }))
        }
    }, [game, hedgehogConfig.party_mode_enabled, members])

    useEffect(() => ensureAllMembersLoaded(), [hedgehogConfig.enabled])

    return hedgehogConfig.enabled ? (
        <>
            <div id="game" className="fixed inset-0" style={{ zIndex: 99999 }} ref={setRef} />
            <MyHedgehogBuddy onClose={() => patchHedgehogConfig({ enabled: false })} />

            {hedgehogConfig.party_mode_enabled
                ? members?.map((member) => {
                      if (member.user.uuid !== user?.uuid && member.user.hedgehog_config) {
                          return <MemberHedgehogBuddy key={member.user.uuid} member={member} />
                      }
                  })
                : null}
        </>
    ) : (
        <></>
    )
}
