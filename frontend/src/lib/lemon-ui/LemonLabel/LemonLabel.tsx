import './LemonLabel.scss'

import clsx from 'clsx'
import { IconInfo } from 'lib/lemon-ui/icons'

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
                            <IconInfo className="text-xl text-muted-alt shrink-0" />
                        </Link>
                    ) : (
                        <span>
                            <IconInfo className="text-xl text-muted-alt shrink-0" />
                        </span>
                    )}
                </Tooltip>
            ) : null}
        </label>
    )
}
