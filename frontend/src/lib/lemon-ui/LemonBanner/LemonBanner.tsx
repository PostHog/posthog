import './LemonBanner.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconInfo, IconSparkles, IconWarning, IconX } from '@posthog/icons'

import { LemonButton, SideAction } from 'lib/lemon-ui/LemonButton'
import { LemonButtonPropsBase } from 'lib/lemon-ui/LemonButton'

import { lemonBannerLogic } from './lemonBannerLogic'

export type LemonBannerAction = SideAction & Pick<LemonButtonPropsBase, 'children'>

export interface LemonBannerProps {
    type: 'info' | 'warning' | 'error' | 'success' | 'ai'
    /** If onClose is provided, a close button will be shown and this callback will be fired when it's clicked. */
    onClose?: () => void
    children: React.ReactNode
    action?: LemonBannerAction
    className?: string
    /** If provided, the banner will be dismissed and hidden when the key is set in localStorage. */
    dismissKey?: string
    /**
     * If left unset, the type-specific icon will show up above a certain width of the banner.
     * If set to a boolean, the icon will either always be hidden or always shown.
     */
    hideIcon?: boolean
    square?: boolean
    icon?: React.ReactNode
}

/** Generic alert message. */
export function LemonBanner({
    type,
    onClose,
    children,
    action,
    className,
    dismissKey = '',
    hideIcon,
    square = false,
    icon,
}: LemonBannerProps): JSX.Element | null {
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
        return null
    }

    return (
        <div
            className={clsx(
                'LemonBanner @container',
                `LemonBanner--${type}`,
                className,
                square && 'LemonBanner--square'
            )}
        >
            <div className="flex flex-wrap items-center gap-2 grow @md:!flex-nowrap @md:!px-1">
                {!hideIcon &&
                    (icon ? (
                        icon
                    ) : type === 'warning' || type === 'error' ? (
                        <IconWarning className={clsx('LemonBanner__icon', hideIcon !== false && 'hidden @md:!block')} />
                    ) : type === 'ai' ? (
                        <IconSparkles
                            className={clsx('LemonBanner__icon', hideIcon !== false && 'hidden @md:!block')}
                        />
                    ) : (
                        <IconInfo className={clsx('LemonBanner__icon', hideIcon !== false && 'hidden @md:!block')} />
                    ))}
                <div className="grow overflow-hidden">{children}</div>
                {/* One action button that keeps its place: full width on its own wrapped row below @md,
                    inline above @md. It never toggles visibility, so a width change during load can't
                    hide the copy under the pointer and swallow the click. */}
                {action && (
                    <LemonButton
                        className="order-last !w-full @md:!order-none @md:!w-auto"
                        type="secondary"
                        {...action}
                    />
                )}
                {showCloseButton && (
                    <LemonButton size="xsmall" icon={<IconX />} onClick={_onClose} aria-label="close" />
                )}
            </div>
        </div>
    )
}
