import React from 'react'
import clsx from 'clsx'
import './LemonRow.scss'
import { Tooltip } from '../Tooltip'

// Implement function type inference for forwardRef,
// so that function components wrapped with forwardRef (i.e. LemonRow) can be generic.
declare module 'react' {
    function forwardRef<T, P>(
        render: (props: P, ref: React.Ref<T>) => React.ReactElement | null
    ): (props: P & React.RefAttributes<T>) => React.ReactElement | null
}

export interface LemonRowPropsBase<T extends keyof JSX.IntrinsicElements>
    extends Omit<React.HTMLProps<JSX.IntrinsicElements[T]>, 'ref'> {
    icon?: React.ReactElement | null
    /** HTML tag to render the row with. */
    tag?: T
    status?: 'success' | 'warning' | 'danger' | 'highlighted'
    /** Extended content, e.g. a description, to show in the lower button area. */
    extendedContent?: string
    /** Tooltip to display on hover. */
    tooltip?: any
    /** Whether the row should take up the parent's full width. */
    fullWidth?: boolean
    /** Whether the row's contents should be centered. */
    center?: boolean
    'data-attr'?: string
}

// This is a union so that a LemonRow can be compact OR have a sideIcon, but not both at once
export type LemonRowProps<T extends keyof JSX.IntrinsicElements> =
    | (LemonRowPropsBase<T> & {
          sideIcon?: null
          compact?: boolean
      })
    | (LemonRowPropsBase<T> & {
          sideIcon?: React.ReactElement | null
          compact?: false
      })

/** Generic UI row component. Can be exploited as a button (see LemonButton) or just as a presentation element. */
function LemonRowInternal<T extends keyof JSX.IntrinsicElements>(
    {
        children,
        icon,
        className,
        tag,
        status,
        extendedContent,
        tooltip,
        sideIcon,
        compact = false,
        fullWidth = false,
        center = false,
        ...props
    }: LemonRowProps<T>,
    ref: React.Ref<JSX.IntrinsicElements[T]>
): JSX.Element {
    const element = React.createElement(
        tag || 'div',
        {
            className: clsx(
                'LemonRow',
                className,
                status && `LemonRow--status-${status}`,
                compact && 'LemonRow--compact',
                fullWidth && 'LemonRow--full-width',
                center && 'LemonRow--center'
            ),
            ...props,
            ref,
        },
        <>
            <div className="LemonRow__main-area">
                {icon && <span className="LemonRow__icon">{icon}</span>}
                {children && <div className="LemonRow__content">{children}</div>}
                {sideIcon && <span className="LemonRow__icon">{sideIcon}</span>}
            </div>
            {extendedContent && <div className="LemonRow__extended-area">{extendedContent}</div>}
        </>
    )
    return tooltip ? <Tooltip title={tooltip}>{element}</Tooltip> : element
}
export const LemonRow = React.forwardRef(LemonRowInternal)

export interface LemonSpacerProps {
    /** Twice the default amount of margin. */
    large?: boolean
}

/** A separator ideal for being sandwiched between LemonRows. */
export function LemonSpacer({ large = false }: LemonSpacerProps): JSX.Element {
    return <div className={clsx('LemonSpacer', large && 'LemonSpacer--large')} />
}
