import clsx from 'clsx'
import { IconClose, IconEllipsis } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonButtonDropdown } from 'lib/lemon-ui/LemonButton/LemonButton'
import './LemonTag.scss'

export type LemonTagPropsType = 'highlight' | 'warning' | 'danger' | 'success' | 'default' | 'purple' | 'none'
interface LemonTagProps extends React.HTMLAttributes<HTMLDivElement> {
    type?: LemonTagPropsType
    children: React.ReactNode
    icon?: JSX.Element
    closable?: boolean
    onClose?: () => void
    popover?: LemonButtonDropdown
}

export function LemonTag({
    type = 'default',
    children,
    className,
    icon,
    closable,
    onClose,
    popover,
    ...props
}: LemonTagProps): JSX.Element {
    return (
        <div className={clsx('LemonTag', { clickable: !!props.onClick }, type, className)} {...props}>
            {icon && <span className="LemonTag__icon">{icon}</span>}
            {children}
            {popover?.overlay && (
                <LemonButtonWithDropdown
                    dropdown={popover}
                    status="stealth"
                    size="small"
                    className="LemonTag__right-button"
                    icon={<IconEllipsis />}
                />
            )}
            {closable && (
                <LemonButton onClick={onClose} status="primary" size="small" className="LemonTag__right-button">
                    <IconClose />
                </LemonButton>
            )}
        </div>
    )
}
