import React from 'react'
import { useValues } from 'kea'
import { IconExternalLink, IconGroups } from 'lib/components/icons'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import './GroupsIntroduction.scss'
import { LemonButton } from 'lib/components/LemonButton'

interface Props {
    access: GroupsAccessStatus.NoAccess | GroupsAccessStatus.HasAccess | GroupsAccessStatus.HasGroupTypes
}

export function GroupsIntroduction({ access }: Props): JSX.Element {
    let title, subtext, primaryButton, secondaryButton

    const { upgradeLink } = useValues(groupsAccessLogic)

    const upgradeButton = (
        <LemonButton
            to={upgradeLink}
            type="primary"
            data-attr="group-analytics-upgrade"
            className="groups-introduction__action-button"
        >
            Upgrade to get Group analytics
        </LemonButton>
    )

    const learnMoreButton = (
        <LemonButton
            type={access === GroupsAccessStatus.HasAccess ? 'primary' : 'highlighted'}
            to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-page"
            target="_blank"
            rel="noopener"
            data-attr="group-analytics-learn-more"
            className="groups-introduction__action-button"
        >
            Learn how to track groups in PostHog <IconExternalLink style={{ marginLeft: 8 }} />
        </LemonButton>
    )

    if (access === GroupsAccessStatus.NoAccess) {
        title = (
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
        primaryButton = upgradeButton
        secondaryButton = learnMoreButton
    } else if (access === GroupsAccessStatus.HasAccess) {
        title = <>You're almost done!</>
        subtext = <>Learn how to track groups in your code</>
        primaryButton = learnMoreButton
    } else {
        // HasGroupTypes
        title = <>Looks like you're tracking groups!</>
        subtext = <>Upgrade today to use groups in Insights.</>
        primaryButton = upgradeButton
    }

    return (
        <div className="groups-introduction">
            <IconGroups style={{ fontSize: 52, color: 'var(--muted-alt)' }} />
            <h2>{title}</h2>
            <div className="groups-introduction__subtext">{subtext}</div>
            {primaryButton}
            {secondaryButton}
        </div>
    )
}
