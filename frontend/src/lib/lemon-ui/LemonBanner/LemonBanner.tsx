import './LemonBanner.scss'
import { IconClose, IconInfo, IconWarning } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { LemonButton, SideAction } from 'lib/lemon-ui/LemonButton'
import { LemonButtonPropsBase } from 'lib/lemon-ui/LemonButton/LemonButton'

export type LemonBannerAction = SideAction & Pick<LemonButtonPropsBase, 'children'>

export interface LemonBannerProps {
    type: 'info' | 'warning' | 'error' | 'success'
    /** If onClose is provided, a close button will be shown and this callback will be fired when it's clicked. */
    onClose?: () => void
    children: React.ReactNode
    action?: LemonBannerAction
    className?: string
}

/** Generic alert message. */
export function LemonBanner({ type, onClose, children, action, className }: LemonBannerProps): JSX.Element {
    return (
        <div className={clsx('LemonBanner', `LemonBanner--${type}`, className)}>
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
