import './LemonCard.scss'

import { IconX } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

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
            className={cn(
                'LemonCard border rounded p-6 bg-surface-primary relative',
                {
                    'LemonCard--hoverEffect': hoverEffect,
                    'border-2 border-accent': focused,
                    'border-primary': !focused,
                    'cursor-pointer': !!onClick && !focused,
                },
                className
            )}
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
