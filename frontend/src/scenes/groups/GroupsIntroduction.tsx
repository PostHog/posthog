import React from 'react'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'

interface Props {
    access: GroupsAccessStatus.NoAccess | GroupsAccessStatus.HasAccess | GroupsAccessStatus.HasGroupTypes
}

export function GroupsIntroduction({ access }: Props): JSX.Element {
    let header, subtext

    if (access === GroupsAccessStatus.NoAccess) {
        header = (
            <>
                Introducing <span className="highlight">Group Analytics</span>!
            </>
        )
        subtext = (
            <>
                Analyze how groups interact with your product as a whole instead of individual users (e.g. retention by
                companies instead of by users)
            </>
        )
    } else if (access === GroupsAccessStatus.HasAccess) {
        header = <>You're almost done!</>
        subtext = <>Learn how to track groups in your code</>
    } else {
        // HasGroupTypes
        header = <>Looks like you're tracking groups!</>
        subtext = <>Upgrade today to use groups in Insights.</>
    }

    return (
        <PayGatePage
            header={header}
            featureKey="group-analytics"
            caption={subtext}
            docsLink="https://posthog.com/docs/user-guides/group-analytics"
            hideUpgradeButton={access === GroupsAccessStatus.HasAccess}
        />
    )
}
