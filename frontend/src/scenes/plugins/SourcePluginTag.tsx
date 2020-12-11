import React from 'react'
import { Tag } from 'antd'

export function SourcePluginTag({ title, style }: { title?: string; style?: React.CSSProperties }): JSX.Element {
    return (
        <Tag color="volcano" style={style}>
            {title || 'Source Plugin'}
        </Tag>
    )
}
