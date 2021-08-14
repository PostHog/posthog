import React, { useState } from 'react'
import { Tooltip as AntdTooltip } from 'antd'
import { TooltipProps } from 'antd/lib/tooltip'
import { useDebounce } from 'use-debounce'

const DEFAULT_DELAY = 500 //ms

// CAUTION: any changes here will affect tooltips across the entire app.
export function Tooltip({ children, visible, ...props }: TooltipProps): JSX.Element {
    const [localVisible, setVisible] = useState(visible)
    const [debouncedLocalVisible] = useDebounce(visible ?? localVisible, DEFAULT_DELAY)

    // If child not a valid element (string or string + ReactNode, Fragment), antd wraps children in a span.
    // See https://github.com/ant-design/ant-design/blob/master/components/tooltip/index.tsx#L226
    const child = React.isValidElement(children) ? children : <span>{children}</span>

    return (
        <AntdTooltip {...props} mouseEnterDelay={DEFAULT_DELAY} visible={localVisible && debouncedLocalVisible}>
            {React.cloneElement(child, {
                onMouseEnter: () => setVisible(true),
                onMouseLeave: () => setVisible(false),
            })}
        </AntdTooltip>
    )
}
