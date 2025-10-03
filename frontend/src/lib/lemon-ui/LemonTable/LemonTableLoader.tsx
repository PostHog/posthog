import './LemonTableLoader.scss'

import React, { useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

export function LemonTableLoader({
    loading = false,
    tag = 'div',
    placement = 'bottom',
}: {
    loading?: boolean
    /** @default 'div' */
    tag?: 'div' | 'th'
    /** @default 'bottom' */
    placement?: 'bottom' | 'top'
}): JSX.Element {
    const nodeRef = useRef<HTMLElement>(null)
    return (
        <CSSTransition
            in={loading}
            timeout={200}
            classNames="LemonTableLoader-"
            appear
            mountOnEnter
            unmountOnExit
            nodeRef={nodeRef}
        >
            {React.createElement(tag, {
                ref: nodeRef,
                className: `LemonTableLoader ${placement === 'top' ? 'top-0' : '-bottom-px'}`,
            })}
        </CSSTransition>
    )
}
