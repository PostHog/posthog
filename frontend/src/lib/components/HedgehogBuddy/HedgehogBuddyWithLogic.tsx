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
    const [game, setGame] = useState<HedgeHogMode | null>(null)

    const onRef = async (ref: HTMLDivElement | null): Promise<void> => {
        if (ref) {
            const hedgeHogMode = new HedgeHogMode({
                assetsUrl: '/static/hedgehog-mode/',
                platformSelector: '.border',
            })
            try {
                await hedgeHogMode.render(ref)
                setGame(hedgeHogMode)
            } catch (e) {
                console.error('Error rendering hedgehog mode', e)
            }
        }
    }

    useEffect(() => ensureAllMembersLoaded(), [hedgehogConfig.enabled])

    return hedgehogConfig.enabled ? (
        <>
            <div id="game" className="fixed inset-0 z-20" ref={(r) => void onRef(r)} />
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
