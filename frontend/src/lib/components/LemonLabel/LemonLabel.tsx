import './LemonLabel.scss'
import React from 'react'
import { Tooltip } from '../Tooltip'
import { IconInfo } from '../icons'
import clsx from 'clsx'

export interface LemonLabelProps
    extends Pick<React.LabelHTMLAttributes<HTMLLabelElement>, 'htmlFor' | 'form' | 'children' | 'className'> {
    info?: React.ReactNode
    showOptional?: boolean
}

export function LemonLabel({ children, info, className, showOptional, ...props }: LemonLabelProps): JSX.Element {
    return (
        <label className={clsx('LemonLabel', className)} {...props}>
            {children}

            {showOptional ? <span>(optional)</span> : null}

            {info ? (
                <Tooltip title={info}>
                    <IconInfo className="text-xl text-muted-alt" />
                </Tooltip>
            ) : null}
        </label>
    )
}
