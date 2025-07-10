import './LemonLabel.scss'

import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'

import { Link, LinkProps } from '../Link'
import { Tooltip } from '../Tooltip'

export interface LemonLabelProps
    extends Pick<React.LabelHTMLAttributes<HTMLLabelElement>, 'id' | 'htmlFor' | 'form' | 'children' | 'className'> {
    info?: React.ReactNode
    infoLink?: LinkProps['to']
    showOptional?: boolean
    onExplanationClick?: () => void
    htmlFor?: string
}

export function LemonLabel({
    children,
    info,
    className,
    showOptional,
    onExplanationClick,
    infoLink,
    htmlFor,
    ...props
}: LemonLabelProps): JSX.Element {
    return (
        <label className={clsx('LemonLabel', className)} htmlFor={htmlFor} {...props}>
            {children}

            {showOptional ? <span className="LemonLabel__extra">(optional)</span> : null}

            {onExplanationClick ? (
                <Link onClick={onExplanationClick}>
                    <span className="LemonLabel__extra">(what is this?)</span>
                </Link>
            ) : null}

            {info ? (
                <Tooltip title={info}>
                    {infoLink ? (
                        <Link to={infoLink} target="_blank" className="inline-flex">
                            <IconInfo className="text-secondary shrink-0 text-xl" />
                        </Link>
                    ) : (
                        <IconInfo className="text-secondary shrink-0 text-xl" />
                    )}
                </Tooltip>
            ) : null}
        </label>
    )
}
