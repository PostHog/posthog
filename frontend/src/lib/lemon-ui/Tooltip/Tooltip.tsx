// eslint-disable-next-line no-restricted-imports
import { Tooltip as AntdTooltip } from 'antd'
import { TooltipProps as AntdTooltipProps } from 'antd/lib/tooltip'
import { useFloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import React, { useState } from 'react'
import { useDebounce } from 'use-debounce'

const DEFAULT_DELAY_MS = 500

export type TooltipProps = AntdTooltipProps & {
    delayMs?: number
}

/** Extension of Ant Design's Tooltip that enables a delay.
 *
 * Caveat: doesn't work with disabled elements due to lack of workaround that Ant Design uses.
 * See https://github.com/ant-design/ant-design/blob/master/components/tooltip/index.tsx#L82-L130.
 */
// CAUTION: Any changes here will affect tooltips across the entire app.
export function Tooltip({ children, visible, delayMs = DEFAULT_DELAY_MS, ...props }: TooltipProps): JSX.Element {
    const [localVisible, setVisible] = useState(false)
    const [debouncedLocalVisible] = useDebounce(visible ?? localVisible, delayMs)

    const floatingContainer = useFloatingContainerContext()?.current

    if (!('mouseEnterDelay' in props)) {
        // If not preserving default behavior and mouseEnterDelay is not already provided, we use a custom default here
        props.mouseEnterDelay = delayMs
    }

    // If child is not a valid element (string or string + ReactNode, Fragment), antd wraps children in a span.
    // See https://github.com/ant-design/ant-design/blob/master/components/tooltip/index.tsx#L226
    const child = React.isValidElement(children) ? children : <span>{children}</span>

    const derivedVisible = typeof visible === 'undefined' ? localVisible && debouncedLocalVisible : visible

    return props.title ? (
        <AntdTooltip
            {...props}
            getPopupContainer={floatingContainer ? () => floatingContainer : undefined}
            visible={derivedVisible}
        >
            {React.cloneElement(child, {
                onMouseEnter: () => {
                    child.props.onMouseEnter?.()
                    if (typeof visible === 'undefined') {
                        setVisible(true)
                    }
                },
                onMouseLeave: () => {
                    child.props.onMouseLeave?.()
                    if (typeof visible === 'undefined') {
                        setVisible(false)
                    }
                },
            })}
        </AntdTooltip>
    ) : (
        child
    )
}
