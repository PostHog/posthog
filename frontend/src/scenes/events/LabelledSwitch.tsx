import { Space, Switch, Typography } from 'antd'
import React from 'react'
import './LabelledSwitch.scss'

export interface LabelledSwitchProps {
    label: string
    enabled: boolean
    onToggle: (x: boolean) => void
    align: 'right' | 'left'
}

export function LabelledSwitch({ align, enabled, label, onToggle }: LabelledSwitchProps): JSX.Element {
    return (
        <Space className="labelled-switch" align="center" style={align === 'right' ? { float: 'right' } : {}}>
            <div onClick={() => onToggle(!enabled)}>
                <Typography.Text ellipsis={true} className="labelled-switch-title">
                    {label}
                </Typography.Text>
                <Switch checked={enabled} onChange={onToggle} />
            </div>
        </Space>
    )
}
