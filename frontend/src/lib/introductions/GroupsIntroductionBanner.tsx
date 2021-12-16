import React from 'react'
import { useValues } from 'kea'
import { LinkButton } from 'lib/components/LinkButton'
import { Link } from 'lib/components/Link'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

export function GroupsIntroductionBanner(): JSX.Element | null {
    const { groupsAccessStatus, upgradeLink } = useValues(groupsAccessLogic)

    const showUpgradeButton = [GroupsAccessStatus.NoAccess, GroupsAccessStatus.HasGroupTypes].includes(
        groupsAccessStatus
    )

    let introductionSegment = (
        <>
            <strong>🎉 Introducing Group Analytics!</strong> Analyze how groups interact with your product as a whole.
        </>
    )
    if (groupsAccessStatus === GroupsAccessStatus.HasGroupTypes) {
        introductionSegment = (
            <>
                <strong>🎉 Looks like you're tracking groups!</strong> Upgrade today to run group-based analytics.
            </>
        )
    }

    return (
        <div>
            {introductionSegment}
            {showUpgradeButton && (
                <LinkButton to={upgradeLink} className="GroupsAnnouncement__button" data-attr="group-analytics-upgrade">
                    Upgrade
                </LinkButton>
            )}
            <Link
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                target="_blank"
                data-attr="group-analytics-learn-more"
                style={{ marginLeft: 8 }}
            >
                Learn more
            </Link>
        </div>
    )
}
