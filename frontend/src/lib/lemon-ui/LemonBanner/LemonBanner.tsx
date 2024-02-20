import './LemonBanner.scss'

import { IconWarning, IconX } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconInfo } from 'lib/lemon-ui/icons'
import { LemonButton, SideAction } from 'lib/lemon-ui/LemonButton'
import { LemonButtonPropsBase } from 'lib/lemon-ui/LemonButton'

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

    const { ref: wrapperRef, size } = useResizeBreakpoints({
        0: 'compact',
        400: 'normal',
    })

    const _onClose = (): void => {
        if (dismissKey) {
            dismiss()
        }
        onClose?.()
    }

    if (isDismissed) {
        return <></>
    }

    const isCompact = size === 'compact'

    return (
        <div
            className={clsx('LemonBanner', `LemonBanner--${type}`, isCompact && 'LemonBanner--compact', className)}
            ref={wrapperRef}
        >
            <div className="flex items-center gap-2 grow">
                {!isCompact ? (
                    type === 'warning' || type === 'error' ? (
                        <IconWarning className="LemonBanner__icon" />
                    ) : (
                        <IconInfo className="LemonBanner__icon" />
                    )
                ) : null}
                <div className="grow overflow-hidden">{children}</div>
                {!isCompact && action && <LemonButton type="secondary" {...action} />}
                {showCloseButton && <LemonButton size="small" icon={<IconX />} onClick={_onClose} aria-label="close" />}
            </div>
            {isCompact && action && <LemonButton type="secondary" fullWidth {...action} />}
        </div>
    )
}
