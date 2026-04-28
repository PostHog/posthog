import './LemonTableLoader.scss'

import React from 'react'

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
}): JSX.Element | null {
    if (!loading) {
        return null
    }
    return React.createElement(tag, {
        className: `LemonTableLoader LemonTableLoader--active ${placement === 'top' ? 'top-0' : '-bottom-px'}`,
    })
}
