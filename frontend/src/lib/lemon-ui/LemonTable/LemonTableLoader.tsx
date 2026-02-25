import './LemonTableLoader.scss'

import { useRef, createElement } from 'react'
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
    const nodeRef = useRef<HTMLDivElement | HTMLTableCellElement>(null)

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
            {createElement(tag, {
                ref: nodeRef,
                className: `LemonTableLoader ${placement === 'top' ? 'top-0' : '-bottom-px'}`,
            })}
        </CSSTransition>
    )
}
