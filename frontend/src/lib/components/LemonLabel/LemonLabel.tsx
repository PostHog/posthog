import './LemonLabel.scss'
import React from 'react'
import { Tooltip } from '../Tooltip'
import { IconInfo } from '../icons'
import clsx from 'clsx'

export interface LemonLabelProps
    extends Pick<React.LabelHTMLAttributes<HTMLLabelElement>, 'htmlFor' | 'form' | 'children' | 'className'> {
    info?: React.ReactNode
}

export function LemonLabel({ children, info, className, ...props }: LemonLabelProps): JSX.Element {
    return (
        <label className={clsx('LemonLabel', className)} {...props}>
            {children}

            {info ? (
                <Tooltip title={info}>
                    <IconInfo className="text-xl text-muted-alt" />
                </Tooltip>
            ) : null}
        </label>
    )
}
