import React, { useState } from 'react'
import { Tooltip as AntdTooltip } from 'antd'
import { TooltipProps as AntdTooltipProps } from 'antd/lib/tooltip'
import { useDebounce } from 'use-debounce'

const DEFAULT_DELAY_MS = 500

export type TooltipProps = AntdTooltipProps & {
    /** Whether Ant Design's default Tooltip behavior should be used instead of PostHog's. */
    isDefaultTooltip?: boolean
    delayMs?: number
}

/** Extension of Ant Design's Tooltip that enables a delay.
 *
 * Caveat: doesn't work with disabled elements due to lack of workaround that Ant Design uses.
 * See https://github.com/ant-design/ant-design/blob/master/components/tooltip/index.tsx#L82-L130.
 */
// CAUTION: Any changes here will affect tooltips across the entire app.
export function Tooltip({
    children,
    visible,
    isDefaultTooltip = false,
    delayMs = DEFAULT_DELAY_MS,
    ...props
}: TooltipProps): JSX.Element {
    const [localVisible, setVisible] = useState(visible)
    const [debouncedLocalVisible] = useDebounce(visible ?? localVisible, delayMs)

    if (!isDefaultTooltip && !('mouseEnterDelay' in props)) {
        // If not preserving default behavior and mouseEnterDelay is not already provided, we use a custom default here
        props.mouseEnterDelay = delayMs
    }

    // If child is not a valid element (string or string + ReactNode, Fragment), antd wraps children in a span.
    // See https://github.com/ant-design/ant-design/blob/master/components/tooltip/index.tsx#L226
    const child = React.isValidElement(children) ? children : <span>{children}</span>

    return (
        <AntdTooltip {...props} visible={isDefaultTooltip ? visible : localVisible && debouncedLocalVisible}>
            {React.cloneElement(child, {
                onMouseEnter: () => setVisible(true),
                onMouseLeave: () => setVisible(false),
            })}
        </AntdTooltip>
    )
}
