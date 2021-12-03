import React from 'react'
import { useValues } from 'kea'
import { LinkButton } from 'lib/components/LinkButton'
import { Link } from 'lib/components/Link'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'

export function GroupsIntroductionBanner(): JSX.Element | null {
    const { upgradeLink } = useValues(groupsAccessLogic)

    return (
        <div>
            <strong>🎉 Introducing group analytics!</strong> Analyze how groups interact with your product as a whole.
            <LinkButton to={upgradeLink} className="GroupsAnnouncement__button" data-attr="group-analytics-upgrade">
                Upgrade
            </LinkButton>
            <Link
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                target="_blank"
                data-attr="group-analytics-learn-more"
            >
                Learn more
            </Link>
        </div>
    )
}
