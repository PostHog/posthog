import React from 'react'
import clsx from 'clsx'
import { Tooltip } from '../Tooltip'
import { IconInfo } from '../icons'

export interface LemonLabelProps
    extends Pick<React.LabelHTMLAttributes<HTMLLabelElement>, 'htmlFor' | 'form' | 'children'> {
    info?: string | JSX.Element
}

export function LemonLabel({ children, info, ...props }: LemonLabelProps): JSX.Element {
    return (
        <label className={'LemonLabel inline-flex items-center gap-2'} {...props}>
            <span className="font-semibold">{children}</span>

            {info ? (
                <Tooltip title={info}>
                    <IconInfo className="text-xl text-muted-alt" />
                </Tooltip>
            ) : null}
        </label>
    )
}
