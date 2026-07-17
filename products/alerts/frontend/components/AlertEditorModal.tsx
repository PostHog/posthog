import { ReactNode } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import {
    AlertEditorActions,
    AlertEditorHeader,
    type AlertEditorProps,
} from 'products/alerts/frontend/components/AlertEditor'

interface AlertEditorModalProps {
    isOpen: boolean | undefined
    onClose?: () => void
    children: ReactNode
    width?: number
    loading?: boolean
    inline?: boolean
    closable?: boolean
}

export function AlertEditorModal({
    isOpen,
    onClose,
    children,
    width = 720,
    loading = false,
    inline = false,
    closable = true,
}: AlertEditorModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} width={width} simple title="" inline={inline} closable={closable}>
            {loading ? <SpinnerOverlay /> : children}
        </LemonModal>
    )
}

type AlertEditorModalLayoutProps = Omit<AlertEditorProps, 'className'>

export function AlertEditorModalLayout({
    title,
    description,
    onBack,
    children,
    ...actionsProps
}: AlertEditorModalLayoutProps): JSX.Element {
    return (
        <>
            <LemonModal.Header>
                <AlertEditorHeader title={title} description={description} onBack={onBack} />
            </LemonModal.Header>
            <LemonModal.Content>{children}</LemonModal.Content>
            <LemonModal.Footer>
                <AlertEditorActions {...actionsProps} />
            </LemonModal.Footer>
        </>
    )
}
