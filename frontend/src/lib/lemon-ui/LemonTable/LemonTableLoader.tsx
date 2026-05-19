import './LemonTableLoader.scss'

import React from 'react'

import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'

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
    const ref = useCancelAnimationsOnUnmount<HTMLDivElement>()
    if (!loading) {
        return null
    }
    return React.createElement(tag, {
        ref,
        className: `LemonTableLoader LemonTableLoader--active ${placement === 'top' ? 'top-0' : '-bottom-px'}`,
    })
}
