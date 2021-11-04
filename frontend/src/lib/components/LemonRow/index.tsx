import React from 'react'
import clsx from 'clsx'
import './LemonRow.scss'
import { Tooltip } from '../Tooltip'

export interface LemonRowPropsBase<T extends keyof JSX.IntrinsicElements>
    extends React.HTMLProps<JSX.IntrinsicElements[T]> {
    icon?: React.ReactElement
    tag?: T
    status?: 'success' | 'warning' | 'danger' // CSS variable colors
    tooltip?: string
    fullWidth?: boolean
}

// This is a union so that a LemonRow can be compact OR have a sideIcon, but not both at once
export type LemonRowProps<T extends keyof JSX.IntrinsicElements> =
    | (LemonRowPropsBase<T> & {
          sideIcon?: null
          compact?: boolean
      })
    | (LemonRowPropsBase<T> & {
          sideIcon?: React.ReactElement
          compact?: false
      })

/** Generic UI row component. Can be exploited as a button (see LemonButton) or just as a presentation element. */
export function LemonRow<T extends keyof JSX.IntrinsicElements = 'div'>({
    children,
    icon,
    className,
    tag,
    status,
    tooltip,
    sideIcon,
    compact = false,
    fullWidth = false,
    ...props
}: LemonRowProps<T>): JSX.Element {
    const element = React.createElement(
        tag || 'div',
        {
            className: clsx(
                'LemonRow',
                className,
                status && `LemonRow--status-${status}`,
                compact && 'LemonRow--compact',
                fullWidth && 'LemonRow--full-width'
            ),
            ...props,
        },
        <>
            {icon && <span className="LemonRow__icon">{icon}</span>}
            <div className="LemonRow__content">{children}</div>
            {sideIcon && <span className="LemonRow__icon">{sideIcon}</span>}
        </>
    )
    return tooltip ? <Tooltip title={tooltip}>{element}</Tooltip> : element
}
