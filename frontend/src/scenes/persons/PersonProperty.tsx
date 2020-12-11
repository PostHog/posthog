import React, { useMemo } from 'react'
import { BulbOutlined, NumberOutlined } from '@ant-design/icons'
import { IconText } from 'lib/components/icons'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Tooltip } from 'antd'

export function PersonProperty({
    name,
    value,
}: {
    name: string
    value: string | number | boolean | null
}): JSX.Element {
    const type = useMemo(() => {
        if (value === true || value === false) {
            return 'boolean'
        } else if (typeof value === 'number') {
            return 'number'
        }
        return 'string'
    }, [value])

    const icon = useMemo(() => {
        if (type === 'boolean') {
            return (
                <Tooltip title="Property of type boolean">
                    <BulbOutlined />
                </Tooltip>
            )
        } else if (type === 'number') {
            return (
                <Tooltip title="Property of type number">
                    <NumberOutlined />
                </Tooltip>
            )
        }
        return (
            <Tooltip title="Property of type string">
                {' '}
                <IconText />
            </Tooltip>
        )
    }, [type])

    return (
        <div className="person-property">
            <label>
                <PropertyKeyInfo value={name} />
                <span style={{ marginLeft: 4, color: 'var(--primary)' }}>{icon}</span>
            </label>
            <div className="val">{value?.toString()}</div>
        </div>
    )
}
