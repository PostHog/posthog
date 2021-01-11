import { Tooltip } from 'antd'
import moment from 'moment'
import React from 'react'

export function Created({ timestamp }: { timestamp: string }): JSX.Element {
    return <Tooltip title={moment(timestamp).format('LLL')}>{moment(timestamp).fromNow()}</Tooltip>
}
