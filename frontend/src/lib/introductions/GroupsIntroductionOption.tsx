import { useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { IconLock } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import Select from 'rc-select'

// TODO: Remove, but de-ant FeatureFlagReleaseConditions first
export function GroupsIntroductionOption({ value }: { value: any }): JSX.Element | null {
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    if (
        ![GroupsAccessStatus.HasAccess, GroupsAccessStatus.HasGroupTypes, GroupsAccessStatus.NoAccess].includes(
            groupsAccessStatus
        )
    ) {
        return null
    }

    return (
        <Select.Option
            key="groups"
            value={value}
            disabled
            style={{
                height: '100%',
                width: '100%',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                backgroundColor: 'var(--side)',
                color: 'var(--muted)',
            }}
        >
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
        </Select.Option>
    )
}
