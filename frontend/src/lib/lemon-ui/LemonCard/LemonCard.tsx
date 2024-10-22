import './LemonCard.scss'

import { IconX } from '@posthog/icons'

import { LemonButton } from '../LemonButton'

export interface LemonCardProps {
    hoverEffect?: boolean
    className?: string
    children?: React.ReactNode
    onClick?: () => void
    focused?: boolean
    'data-attr'?: string
    closeable?: boolean
    onClose?: () => void
}

export function LemonCard({
    hoverEffect = true,
    className,
    children,
    onClick,
    focused,
    closeable,
    onClose,
    ...props
}: LemonCardProps): JSX.Element {
    return (
        <div
            className={`LemonCard ${hoverEffect && 'LemonCard--hoverEffect'} border ${
                focused ? 'border-2 border-primary' : 'border-border'
            } rounded p-6 bg-bg-light ${onClick && !focused ? 'cursor-pointer' : ''} ${className}`}
            onClick={onClick}
            {...props}
        >
            {closeable ? (
                <div className="absolute top-2 right-2">
                    <LemonButton
                        icon={<IconX />}
                        onClick={(e) => {
                            e.stopPropagation()
                            onClose?.()
                        }}
                        type="tertiary"
                        size="xsmall"
                    />
                </div>
            ) : null}
            {children}
        </div>
    )
}
