import './LemonBanner.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconClose, IconInfo, IconWarning } from 'lib/lemon-ui/icons'
import { LemonButton, SideAction } from 'lib/lemon-ui/LemonButton'
import { LemonButtonPropsBase } from 'lib/lemon-ui/LemonButton/LemonButton'

import { lemonBannerLogic } from './lemonBannerLogic'

export type LemonBannerAction = SideAction & Pick<LemonButtonPropsBase, 'children'>

export interface LemonBannerProps {
    type: 'info' | 'warning' | 'error' | 'success'
    /** If onClose is provided, a close button will be shown and this callback will be fired when it's clicked. */
    onClose?: () => void
    children: React.ReactNode
    action?: LemonBannerAction
    className?: string
    /** If provided, the banner will be dismissed and hidden when the key is set in localStorage. */
    dismissKey?: string
}

/** Generic alert message. */
export function LemonBanner({
    type,
    onClose,
    children,
    action,
    className,
    dismissKey = '',
}: LemonBannerProps): JSX.Element {
    const logic = lemonBannerLogic({ dismissKey })
    const { isDismissed } = useValues(logic)
    const { dismiss } = useActions(logic)
    const showCloseButton = dismissKey || onClose

    const _onClose = (): void => {
        if (dismissKey) {
            dismiss()
        }
        onClose?.()
    }

    if (isDismissed) {
        return <></>
    }

    return (
        <div className={clsx('LemonBanner', `LemonBanner--${type}`, className)}>
            {type === 'warning' || type === 'error' ? <IconWarning /> : <IconInfo />}
            <div className="flex-1">{children}</div>
            {action && <LemonButton type="secondary" {...action} />}
            {showCloseButton && (
                <LemonButton
                    status="primary-alt"
                    size="small"
                    icon={<IconClose />}
                    onClick={_onClose}
                    aria-label="close"
                />
            )}
        </div>
    )
}
