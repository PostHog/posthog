import React from 'react'
import { Tag } from 'antd'

export function CommunityPluginTag({ isCommunity }: { isCommunity?: boolean }): JSX.Element {
    return (
        <Tag
            color={isCommunity ? 'green' : 'blue'}
            style={{ maxWidth: '30%', position: 'absolute', right: 15, top: 15 }}
        >
            {isCommunity ? 'Community' : 'Core Team'}
        </Tag>
    )
}
