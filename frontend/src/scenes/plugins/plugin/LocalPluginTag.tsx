import React from 'react'
import { Tag } from 'antd'
import { copyToClipboard } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'

export function LocalPluginTag({
    url,
    title,
    style,
}: {
    url: string
    title?: string
    style?: React.CSSProperties
}): JSX.Element {
    return (
        <Tooltip title={url.substring(5)}>
            <Tag color="purple" onClick={() => copyToClipboard(url.substring(5))} style={style}>
                {title || 'Local Plugin'}
            </Tag>
        </Tooltip>
    )
}
