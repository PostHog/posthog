import { ReactNode, useId, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

export interface ImpersonationReasonModalCancelButton {
    label: string
    status?: 'default' | 'danger'
    onClick: () => void
}

export interface ImpersonationReasonModalProps {
    isOpen: boolean
    onClose?: () => void
    onConfirm: (reason: string) => void | Promise<void>
    title: string
    description?: string
    confirmText?: string
    loading?: boolean
    children?: ReactNode
    cancelButton?: ImpersonationReasonModalCancelButton
    // Forced-choice modals (e.g. session-expired) set closable={false} so the user
    // must pick a footer action — no ESC, no overlay-click, no X button.
    closable?: boolean
    // Renders inline rather than in a portal — used by Storybook to capture snapshots.
    inline?: boolean
}

export function ImpersonationReasonModal({
    isOpen,
    onClose,
    onConfirm,
    title,
    description,
    confirmText = 'Confirm',
    loading = false,
    children,
    cancelButton,
    closable = true,
    inline = false,
}: ImpersonationReasonModalProps): JSX.Element {
    const [reason, setReason] = useState('')
    const reasonInputId = useId()

    const handleConfirm = (): void => {
        onConfirm(reason)
    }

    const handleClose = (): void => {
        setReason('')
        onClose?.()
    }

    const cancel = cancelButton ?? (onClose ? { label: 'Cancel', onClick: handleClose } : null)
    // When the cancel action is destructive, separate it from the confirm action
    // so the danger button isn't adjacent to the primary action.
    const separateCancel = cancel?.status === 'danger'

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            closable={closable}
            inline={inline}
            title={title}
            footer={
                <>
                    {cancel && (
                        <LemonButton type="secondary" status={cancel.status} onClick={cancel.onClick}>
                            {cancel.label}
                        </LemonButton>
                    )}
                    {separateCancel && <div className="flex-1" />}
                    <LemonButton
                        type="primary"
                        onClick={handleConfirm}
                        loading={loading}
                        disabledReason={!loading && !reason.trim() ? 'Please provide a reason' : undefined}
                    >
                        {confirmText}
                    </LemonButton>
                </>
            }
            width={500}
        >
            <div className="space-y-2">
                {description && <p className="text-sm text-secondary">{description}</p>}
                <div>
                    <label className="block mb-1 font-semibold" htmlFor={reasonInputId}>
                        Reason
                    </label>
                    <LemonInput
                        id={reasonInputId}
                        value={reason}
                        onChange={setReason}
                        placeholder="e.g., Customer support request #12345"
                        autoFocus
                    />
                </div>
                {children}
            </div>
        </LemonModal>
    )
}
