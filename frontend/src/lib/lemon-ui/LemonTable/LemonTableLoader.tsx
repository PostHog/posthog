import { CSSTransition } from 'react-transition-group'
import './LemonTableLoader.scss'
import React from 'react'

export function LemonTableLoader({
    loading = false,
    tag = 'div',
}: {
    loading?: boolean
    /** @default 'div' */
    tag?: 'div' | 'th'
}): JSX.Element {
    return (
        <CSSTransition in={loading} timeout={200} classNames="LemonTableLoader-" appear mountOnEnter unmountOnExit>
            {React.createElement(tag, { className: 'LemonTableLoader' })}
        </CSSTransition>
    )
}
