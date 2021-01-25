import React from 'react'
import { Tag } from 'antd'

export function CommunityPluginTag({ isCommunity }: { isCommunity?: boolean }): JSX.Element {
    return <Tag color={isCommunity ? 'green' : 'blue'}>{isCommunity ? 'Community' : 'Official'}</Tag>
}
