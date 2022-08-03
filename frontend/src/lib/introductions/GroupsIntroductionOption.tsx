import React from 'react'
import { useValues } from 'kea'
import { LockOutlined } from '@ant-design/icons'
import Select from 'rc-select'
import { Link } from 'lib/components/Link'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

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
                backgroundColor: 'var(--bg-side)',
                color: 'var(--muted)',
            }}
        >
            <LockOutlined style={{ marginRight: 6, color: 'var(--warning)' }} />
            Unique groups –{' '}
            <Link
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                target="_blank"
                data-attr="group-analytics-learn-more"
                style={{ fontWeight: 600 }}
            >
                Learn more
            </Link>
        </Select.Option>
    )
}
