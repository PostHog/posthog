import React from 'react'
import { useValues } from 'kea'
import { LockOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import Select from 'rc-select'
import { Link } from 'lib/components/Link'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { Tooltip } from 'lib/components/Tooltip'

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
                color: 'var(--text-muted)',
            }}
        >
            <Tooltip title="This is a premium feature. Click to learn more.">
                <Link
                    to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-math-selector-lock"
                    target="_blank"
                    rel="noopener"
                    data-attr="group-analytics-learn-more"
                    style={{ marginRight: 4 }}
                >
                    <LockOutlined style={{ color: 'var(--warning)' }} />
                </Link>
            </Tooltip>
            Unique groups
            <Link
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-math-selector"
                target="_blank"
                rel="noopener"
                data-attr="group-analytics-learn-more"
                style={{ marginLeft: 8, fontWeight: 'bold' }}
            >
                <QuestionCircleOutlined />
            </Link>
        </Select.Option>
    )
}
