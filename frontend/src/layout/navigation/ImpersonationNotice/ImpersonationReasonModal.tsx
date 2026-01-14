import { ReactNode, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

export interface ImpersonationReasonModalProps {
    isOpen: boolean
    onClose: () => void
    onConfirm: (reason: string) => void
    title: string
    description?: string
    confirmText?: string
    children?: ReactNode
}

export function ImpersonationReasonModal({
    isOpen,
    onClose,
    onConfirm,
    title,
    description,
    confirmText = 'Confirm',
    children,
}: ImpersonationReasonModalProps): JSX.Element {
    const [reason, setReason] = useState('')

    const handleConfirm = (): void => {
        onConfirm(reason)
        setReason('')
        onClose()
    }

    const handleClose = (): void => {
        setReason('')
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title={title}
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleConfirm}
                        disabledReason={!reason.trim() ? 'Please provide a reason' : undefined}
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
                    <label className="block mb-1 font-semibold">Reason</label>
                    <LemonInput
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
