import { Dropdown, Input, Menu } from 'antd'
import React from 'react'
import { MetricValueInterface } from './RenderMetricValue'
import { DownOutlined, CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons'

export function RenderMetricValueEdit({ value, value_type }: MetricValueInterface): JSX.Element | string {
    if (value_type === 'bool') {
        return (
            <Dropdown
                overlay={
                    <Menu
                    // onClick={({ key }) => {
                    //     let val = null
                    //     if (key === 't') {
                    //         val = true
                    //     } else if (key === 'f') {
                    //         val = false
                    //     }
                    //     //handleValueChange(val, true)
                    // }}
                    >
                        <Menu.Item key="t">
                            <CheckCircleFilled style={{ color: 'var(--success)' }} /> Yes
                        </Menu.Item>
                        <Menu.Item key="f">
                            <CloseCircleFilled style={{ color: 'var(--danger)' }} /> No
                        </Menu.Item>
                    </Menu>
                }
                trigger={['click']}
            >
                <div className="cursor-pointer">
                    {value ? 'Yes' : 'No'} <DownOutlined style={{ color: 'var(--text-muted)' }} />
                </div>
            </Dropdown>
        )
    }

    return <Input defaultValue={value} type={value_type === 'int' ? 'number' : 'text'} />
}
