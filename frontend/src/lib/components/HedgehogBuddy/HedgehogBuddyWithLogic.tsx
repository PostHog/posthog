import './HedgehogBuddy.scss'

import { HedgeHogMode } from '@posthog/hedgehog-mode'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

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
        game.spawnHedgehog(hedgehogConfig)
        game.isDebugging = true
    }, [game])

    useEffect(() => ensureAllMembersLoaded(), [hedgehogConfig.enabled])

    return hedgehogConfig.enabled ? (
        <>
            <div id="game" className="fixed inset-0 z-50" ref={setRef} />
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
