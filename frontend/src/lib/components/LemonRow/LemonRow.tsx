import React from 'react'
import clsx from 'clsx'
import './LemonRow.scss'
import { Tooltip } from '../Tooltip'
import { Spinner } from '../Spinner/Spinner'

// Implement function type inference for forwardRef,
// so that function components wrapped with forwardRef (i.e. LemonRow) can be generic.
declare module 'react' {
    function forwardRef<T, P>(
        render: (props: P, ref: React.Ref<T>) => React.ReactElement | null
    ): (props: P & React.RefAttributes<T>) => React.ReactElement | null
}

export interface LemonRowPropsBase<T extends keyof JSX.IntrinsicElements>
    extends Omit<React.HTMLProps<JSX.IntrinsicElements[T]>, 'ref'> {
    /** If icon width is relaxed, width of icon box is set to auto. Default icon width is 1em  */
    relaxedIconWidth?: boolean
    icon?: React.ReactElement | null
    /** HTML tag to render the row with. */
    tag?: T
    status?: 'success' | 'warning' | 'danger' | 'highlighted' | 'muted'
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
    /** A compact row is slightly smaller than normal to better look inline with text. */
    compact?: boolean
    'data-attr'?: string
}

export interface LemonRowProps<T extends keyof JSX.IntrinsicElements> extends LemonRowPropsBase<T> {
    sideIcon?: React.ReactElement | null
}

/** Generic UI row component. Can be exploited as a button (see LemonButton) or just as a standard row of content.
 *
 * Do NOT use for general layout if you simply need flexbox though. In that case `display: flex` is much lighter.
 */
export const LemonRow = React.forwardRef(function LemonRowInternal<T extends keyof JSX.IntrinsicElements>(
    {
        children,
        icon,
        relaxedIconWidth = false,
        className,
        tag,
        status,
        extendedContent,
        tooltip,
        sideIcon,
        loading = false,
        compact = false,
        fullWidth = false,
        center = false,
        outlined = false,
        ...props
    }: LemonRowProps<T>,
    ref: React.Ref<JSX.IntrinsicElements[T]>
): JSX.Element {
    const symbolic = children == null || children === false
    if (loading) {
        icon = <Spinner size="sm" />
    }
    const element = React.createElement(
        tag || 'div',
        {
            className: clsx(
                'LemonRow',
                className,
                status && `LemonRow--status-${status}`,
                compact && 'LemonRow--compact',
                symbolic && 'LemonRow--symbolic',
                fullWidth && 'LemonRow--full-width',
                outlined && 'LemonRow--outlined',
                center && 'LemonRow--center'
            ),
            ...props,
            ref,
        },
        <>
            <div className="LemonRow__main-area">
                {icon && (
                    <span
                        className={clsx(
                            'LemonRow__icon',
                            'LemonRow__icon--prefix',
                            relaxedIconWidth && 'LemonRow__icon--relaxed-width'
                        )}
                    >
                        {icon}
                    </span>
                )}
                {!symbolic && <div className="LemonRow__content">{children}</div>}
                {sideIcon && (
                    <span
                        className={clsx(
                            'LemonRow__icon',
                            'LemonRow__icon--suffix',
                            relaxedIconWidth && 'LemonRow__icon--relaxed-width'
                        )}
                    >
                        {sideIcon}
                    </span>
                )}
            </div>
            {extendedContent && <div className="LemonRow__extended-area">{extendedContent}</div>}
        </>
    )
    return tooltip ? <Tooltip title={tooltip}>{element}</Tooltip> : element
})

export interface LemonSpacerProps {
    /** Twice the default amount of margin. */
    large?: boolean
    /** Whether the spacer should be vertical instead of horizontal. */
    vertical?: boolean
    style?: React.CSSProperties
}

/** A separator ideal for being sandwiched between LemonRows. */
export function LemonSpacer({ large = false, vertical = false, style }: LemonSpacerProps): JSX.Element {
    return (
        <div
            className={clsx('LemonSpacer', large && 'LemonSpacer--large', vertical && 'LemonSpacer--vertical')}
            style={style}
        />
    )
}
