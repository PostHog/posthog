import React, { useState } from 'react'
import { Tooltip as AntdTooltip } from 'antd'
import { TooltipProps } from 'antd/lib/tooltip'
import { useDebounce } from 'use-debounce'

const DEFAULT_DELAY = 0.5 //s

// CAUTION: any changes here will affect tooltips across the entire app.
export function Tooltip({ children, visible, ...props }: TooltipProps): JSX.Element {
    const [localVisible, setVisible] = useState(visible)
    const [debouncedLocalVisible] = useDebounce(visible ?? localVisible, DEFAULT_DELAY)

    console.log('VISIBLE', debouncedLocalVisible, localVisible, visible)

    return (
        <AntdTooltip {...props} mouseEnterDelay={DEFAULT_DELAY} visible={debouncedLocalVisible}>
            <span
                onMouseEnter={() => {
                    setVisible(true)
                }}
                onMouseLeave={() => {
                    setVisible(false)
                }}
            >
                {children}
            </span>
        </AntdTooltip>
    )
}
