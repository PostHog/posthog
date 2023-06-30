import { Tag } from 'antd'
import { copyToClipboard } from 'lib/utils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
            <Tag color="purple" onClick={async () => await copyToClipboard(url.substring(5))} style={style}>
                {title || 'Local App'}
            </Tag>
        </Tooltip>
    )
}
