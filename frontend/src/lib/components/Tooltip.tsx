import React, { useState } from 'react'
import { Tooltip as AntdTooltip } from 'antd'
import { TooltipProps } from 'antd/lib/tooltip'
import { useDebounce } from 'use-debounce'

const DEFAULT_DELAY = 500 //ms

type Props = TooltipProps & {
    isDefaultTooltip?: boolean // use Antd's Tooltip without any additional functionality
}

// CAUTION: any changes here will affect tooltips across the entire app.
export function Tooltip({ children, visible, isDefaultTooltip = false, ...props }: Props): JSX.Element {
    const [localVisible, setVisible] = useState(visible)
    const [debouncedLocalVisible] = useDebounce(visible ?? localVisible, DEFAULT_DELAY)

    // If child not a valid element (string or string + ReactNode, Fragment), antd wraps children in a span.
    // See https://github.com/ant-design/ant-design/blob/master/components/tooltip/index.tsx#L226
    const child = React.isValidElement(children) ? children : <span>{children}</span>

    return (
        <AntdTooltip
            mouseEnterDelay={isDefaultTooltip ? undefined : DEFAULT_DELAY} // overridable
            {...props}
            visible={isDefaultTooltip ? visible : localVisible && debouncedLocalVisible}
        >
            {React.cloneElement(child, {
                onMouseEnter: () => setVisible(true),
                onMouseLeave: () => setVisible(false),
            })}
        </AntdTooltip>
    )
}
