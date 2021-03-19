import { Tooltip } from 'antd'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
dayjs.extend(LocalizedFormat)
import React from 'react'

export function Created({ timestamp }: { timestamp: string }): JSX.Element {
    return <Tooltip title={dayjs(timestamp).format('LLL')}>{dayjs(timestamp).fromNow()}</Tooltip>
}
