import './LemonLabel.scss'
import { Tooltip } from '../Tooltip'
import { IconInfo } from '../icons'
import clsx from 'clsx'

export interface LemonLabelProps
    extends Pick<React.LabelHTMLAttributes<HTMLLabelElement>, 'htmlFor' | 'form' | 'children' | 'className'> {
    info?: React.ReactNode
    showOptional?: boolean
    onExplanationClick?: () => void
}

export function LemonLabel({
    children,
    info,
    className,
    showOptional,
    onExplanationClick,
    ...props
}: LemonLabelProps): JSX.Element {
    return (
        <label className={clsx('LemonLabel', className)} {...props}>
            {children}

            {showOptional ? <span className="LemonLabel__extra">(optional)</span> : null}

            {onExplanationClick ? (
                <a onClick={onExplanationClick}>
                    <span className="LemonLabel__extra">(what is this?)</span>
                </a>
            ) : null}

            {info ? (
                <Tooltip title={info}>
                    <IconInfo className="text-xl text-muted-alt shrink-0" />
                </Tooltip>
            ) : null}
        </label>
    )
}
