import React from 'react'
import { Tag } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'

export function CommunityPluginTag({ isCommunity }: { isCommunity?: boolean }): JSX.Element {
    return (
        <Tooltip
            title={
                isCommunity
                    ? 'This app was built by a community memeber, not the PostHog team.'
                    : 'This app was built by the PostHog team.'
            }
        >
            <Tag color={isCommunity ? 'cyan' : 'geekblue'}>{isCommunity ? 'Community' : 'Official'}</Tag>
        </Tooltip>
    )
}
