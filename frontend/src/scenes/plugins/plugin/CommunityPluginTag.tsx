import React from 'react'
import { Tag, Tooltip } from 'antd'

export function CommunityPluginTag({ isCommunity }: { isCommunity?: boolean }): JSX.Element {
    return (
        <Tooltip
            title={
                isCommunity
                    ? 'This plugin was built by a community memeber, not the PostHog team.'
                    : 'This plugin was built by the PostHog team.'
            }
        >
            <Tag color={isCommunity ? 'cyan' : 'geekblue'}>{isCommunity ? 'Community' : 'Official'}</Tag>
        </Tooltip>
    )
}
