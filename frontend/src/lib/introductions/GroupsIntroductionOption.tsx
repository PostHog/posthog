import { IconLock } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'

export function GroupsIntroductionOption(): JSX.Element {
    return (
        <div className="cursor-default">
            <IconLock style={{ marginRight: 6, color: 'var(--warning)' }} />
            Unique groups –{' '}
            <Link
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                target="_blank"
                data-attr="group-analytics-learn-more"
                className="font-semibold"
            >
                Learn more
            </Link>
        </div>
    )
}
