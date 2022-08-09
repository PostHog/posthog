import './LemonLabel.scss'
import React from 'react'
import { Tooltip } from '../Tooltip'
import { IconInfo } from '../icons'

export interface LemonLabelProps
    extends Pick<React.LabelHTMLAttributes<HTMLLabelElement>, 'htmlFor' | 'form' | 'children'> {
    info?: string | JSX.Element
}

export function LemonLabel({ children, info, ...props }: LemonLabelProps): JSX.Element {
    return (
        <label className={'LemonLabel'} {...props}>
            {children}

            {info ? (
                <Tooltip title={info}>
                    <IconInfo className="text-xl text-muted-alt" />
                </Tooltip>
            ) : null}
        </label>
    )
}
