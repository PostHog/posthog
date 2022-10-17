import { Tag } from 'antd'

export function SourcePluginTag({
    title = 'Source Code',
    style,
}: {
    title?: string
    style?: React.CSSProperties
}): JSX.Element {
    return <Tag style={style}>{title}</Tag>
}
