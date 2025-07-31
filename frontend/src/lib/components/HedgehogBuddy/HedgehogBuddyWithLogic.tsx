import './HedgehogBuddy.scss'

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

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

    useEffect(() => ensureAllMembersLoaded(), [hedgehogConfig.enabled, ensureAllMembersLoaded])

    return hedgehogConfig.enabled ? (
        <>
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
