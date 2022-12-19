import './AlertMessage.scss'
import { IconClose, IconInfo, IconWarning } from '../icons'
import clsx from 'clsx'
import { LemonButton, SideAction } from '../LemonButton'
import { LemonButtonPropsBase } from '../LemonButton/LemonButton'

export type AlertMessageAction = SideAction & Pick<LemonButtonPropsBase, 'children'>

export interface AlertMessageProps {
    type: 'info' | 'warning' | 'error' | 'success'
    /** If onClose is provided, a close button will be shown and this callback will be fired when it's clicked. */
    onClose?: () => void
    children: React.ReactNode
    action?: AlertMessageAction
    className?: string
}

/** Generic alert message. */
export function AlertMessage({ type, onClose, children, action, className }: AlertMessageProps): JSX.Element {
    return (
        <div className={clsx('AlertMessage', `AlertMessage--${type}`, className)}>
            {type === 'warning' || type === 'error' ? <IconWarning /> : <IconInfo />}
            <div className="flex-1">{children}</div>
            {action && <LemonButton type="secondary" {...action} />}
            {onClose && (
                <LemonButton
                    status="primary-alt"
                    size="small"
                    icon={<IconClose />}
                    onClick={() => onClose()}
                    aria-label="close"
                />
            )}
        </div>
    )
}
