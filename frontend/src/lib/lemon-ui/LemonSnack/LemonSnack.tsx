import { IconPencil, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useKeyHeld } from 'lib/hooks/useKeyHeld'
import React, { forwardRef } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

export interface LemonSnackProps {
    type?: 'regular' | 'pill'
    children?: React.ReactNode
    onClick?: React.MouseEventHandler
    onClose?: React.MouseEventHandler
    /** If set, `onEdit` replaces `onClose` when Option/Alt is held. The X (close) icon turns into a pencil (edit). */
    onEdit?: React.MouseEventHandler
    title?: string
    wrap?: boolean
    className?: string
    'data-attr'?: string
}

export const LemonSnack: React.FunctionComponent<LemonSnackProps & React.RefAttributes<HTMLSpanElement>> = forwardRef(
    function LemonSnack(
        { type = 'regular', children, wrap, onClick, onClose, onEdit, title, className },
        ref
    ): JSX.Element {
        const isRegular = type === 'regular'
        const isClickable = !!onClick
        return (
            <span
                ref={ref}
                className={clsx(
                    'inline-flex text-primary-alt max-w-full overflow-hidden break-all items-center py-1 leading-5',
                    !wrap && 'whitespace-nowrap',
                    isRegular
                        ? 'bg-primary-highlight px-1.5 rounded'
                        : 'bg-primary-alt-highlight px-4 rounded-full h-8',
                    isClickable && 'cursor-pointer',
                    className
                )}
                onClick={onClick}
            >
                <span
                    className="overflow-hidden text-ellipsis"
                    title={title ?? (typeof children === 'string' ? children : undefined)}
                >
                    {children}
                </span>

                {onClose && (
                    <span className={clsx('LemonSnack__close shrink-0 ml-1', isRegular || '-mr-1')}>
                        {onEdit ? (
                            <SnackCloseButtonWithEdit onClose={onClose} onEdit={onEdit} />
                        ) : (
                            <SnackCloseButton onClose={onClose} />
                        )}
                    </span>
                )}
            </span>
        )
    }
)

function SnackCloseButton({ onClose }: { onClose: React.MouseEventHandler }): JSX.Element {
    return (
        <LemonButton
            size="small"
            noPadding
            icon={<IconX />}
            onClick={(e) => {
                e.stopPropagation()
                onClose(e)
            }}
            tooltip="Click to remove"
        />
    )
}

function SnackCloseButtonWithEdit({
    onClose,
    onEdit,
}: {
    onClose: React.MouseEventHandler
    onEdit: React.MouseEventHandler
}): JSX.Element {
    const altKeyHeld = useKeyHeld('Alt')

    return (
        <LemonButton
            size="small"
            noPadding
            icon={altKeyHeld ? <IconPencil /> : <IconX />}
            onClick={(e) => {
                e.stopPropagation()
                if (altKeyHeld) {
                    onEdit(e)
                } else {
                    onClose(e)
                }
            }}
            tooltip={
                <>
                    Click to remove. Click with <KeyboardShortcut option /> to edit
                </>
            }
        />
    )
}
