import React from 'react'
import { Tooltip as AntdTooltip } from 'antd'
import { TooltipProps } from 'antd/lib/tooltip'

const DEFAULT_DELAY = 0.5 //s

// CAUTION: any changes here will affect tooltips across the entire app.
export function Tooltip({ children, ...props }: TooltipProps): JSX.Element {
    return (
        <AntdTooltip mouseEnterDelay={DEFAULT_DELAY} {...props}>
            {children}
        </AntdTooltip>
    )
}
