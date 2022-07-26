import { Tooltip } from 'lib/components/Tooltip'
import React from 'react'
import { InfoCircleOutlined } from '@ant-design/icons'

export interface EditorFilterItemTitleProps {
    label: string
    tooltip?: JSX.Element
}

export function EditorFilterItemTitle({ label, tooltip }: EditorFilterItemTitleProps): JSX.Element {
    return (
        <div className="mb-05 font-medium">
            {label}
            {tooltip && (
                <Tooltip title={tooltip}>
                    <InfoCircleOutlined className="info-indicator" />
                </Tooltip>
            )}
        </div>
    )
}
