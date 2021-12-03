import React from 'react'
import { GroupsAccessStatus } from '~/models/groupsModel'

interface Props {
    access: GroupsAccessStatus.NoAccess | GroupsAccessStatus.HasAccess | GroupsAccessStatus.HasGroupTypes
}

export function GroupsIntroduction({ access }: Props): JSX.Element {
    let title, subtext, actionButton, learnMoreButton

    if (access === GroupsAccessStatus.NoAccess) {
        title = <>Introducing Group Analytics</>
        subtext = (
            <>
                Analyze how groups interact with your product as a whole instead of individual users (e.g. retention by
                companies instead of by users)
            </>
        )
        actionButton = <>Upgrade to get Group Analytics</>
        learnMoreButton = <>Learn how to track groups in PostHog</>
    } else if (access === GroupsAccessStatus.HasAccess) {
        title = <>You're almost done!</>
        subtext = <>Learn how to track groups in your code</>
    } else {
        title = <>Looks like you're tracking groups!</>
        subtext = <>Upgrade today to use groups in insights.</>
        actionButton = <>Upgrade to get Group Analytics</>
    }

    return (
        <div className="groups-introduction">
            {title}
            {subtext}
            {actionButton}
            {learnMoreButton}
        </div>
    )
}
