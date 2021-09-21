import { Space, Switch, Typography } from 'antd'
import React from 'react'

export interface LabelledSwitchProps {
    label: string
    enabled: boolean
    onToggle: (x: boolean) => void
    align: 'right' | 'left'
}

export function LabelledSwitch(props: LabelledSwitchProps): JSX.Element {
    return (
        <Space className="labelled-switch" align="center" style={props.align === 'right' ? { float: 'right' } : {}}>
            <div onClick={() => props.onToggle(!props.enabled)}>
                <Typography.Text ellipsis={true} className="labelled-switch-title">
                    {props.label}
                </Typography.Text>
                <Switch checked={props.enabled} onChange={props.onToggle} />
            </div>
        </Space>
    )
}
