import './LemonRow.scss'

import clsx from 'clsx'
import React from 'react'

import { Spinner } from '../Spinner/Spinner'
import { Tooltip } from '../Tooltip'

export interface LemonRowPropsBase<T extends keyof JSX.IntrinsicElements>
    extends Omit<React.HTMLProps<JSX.IntrinsicElements[T]>, 'ref' | 'size'> {
    icon?: React.ReactElement | null
    /** HTML tag to render the row with. */
    tag?: T
    status?: 'default' | 'success' | 'warning' | 'danger' | 'highlighted' | 'muted'
    /** Extended content, e.g. a description, to show in the lower button area. */
    extendedContent?: React.ReactNode
    loading?: boolean
    /** Tooltip to display on hover. */
    tooltip?: any
    /** Whether the row should take up the parent's full width. */
    fullWidth?: boolean
    /** Whether the row's contents should be centered. */
    center?: boolean
    /** Whether the element should be outlined with a standard border. */
    outlined?: any
    /** Variation on sizes - default is medium.
     * Small looks better inline with text.
     * Large is a chunkier row.
     * Tall is a chunkier row without changing font size.
     * */
    size?: 'small' | 'medium' | 'tall' | 'large'
    'data-attr'?: string
}

export interface LemonRowProps<T extends keyof JSX.IntrinsicElements = 'div'> extends LemonRowPropsBase<T> {
    sideIcon?: React.ReactElement | false | null
}

/** Generic UI row component. Can be exploited as a button (see LemonButton) or just as a standard row of content.
 *
 * Do NOT use for general layout if you simply need flexbox though. In that case `<div className="flex">` is much lighter.
 */
export const LemonRow = React.forwardRef(function LemonRowInternal<T extends keyof JSX.IntrinsicElements = 'div'>(
    {
        children,
        icon,
        className,
        tag,
        status = 'default',
        extendedContent,
        tooltip,
        sideIcon,
        size = 'medium',
        loading = false,
        fullWidth = false,
        center = false,
        outlined = false,
        disabled = false,
        ...props
    }: LemonRowProps<T>,
    ref: React.Ref<HTMLElement>
): JSX.Element {
    const symbolic = children === null || children === undefined || children === false
    if (loading) {
        icon = <Spinner />
    }
    const element = React.createElement(
        tag || 'div',
        {
            className: clsx(
                'LemonRow',
                className,
                status && status !== 'default' ? `LemonRow--status-${status}` : undefined,
                symbolic && 'LemonRow--symbolic',
                fullWidth && 'LemonRow--full-width',
                disabled && 'LemonRow--disabled',
                outlined && 'LemonRow--outlined',
                center && 'LemonRow--center',
                size === 'large' && 'LemonRow--large',
                size === 'tall' && 'LemonRow--tall',
                size === 'small' && 'LemonRow--small'
            ),
            disabled,
            ...props,
            ref,
        },
        <>
            <div className="LemonRow__main-area">
                {icon && <span className="LemonRow__icon">{icon}</span>}
                {!symbolic && <div className="LemonRow__content">{children}</div>}
                {sideIcon && <span className="LemonRow__icon">{sideIcon}</span>}
            </div>
            {extendedContent && <div className="LemonRow__extended-area">{extendedContent}</div>}
        </>
    )
    return tooltip ? <Tooltip title={tooltip}>{element}</Tooltip> : element
})
