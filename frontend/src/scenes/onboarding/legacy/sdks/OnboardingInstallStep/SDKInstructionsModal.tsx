import { LemonModal } from '@posthog/lemon-ui'

import { SDKInstructionsPanel, type SDKInstructionsPanelProps } from './SDKInstructionsPanel'

interface SDKInstructionsModalProps extends Omit<SDKInstructionsPanelProps, 'onBack'> {
    isOpen: boolean
    onClose: () => void
}

export function SDKInstructionsModal({ isOpen, onClose, ...panelProps }: SDKInstructionsModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple>
            <SDKInstructionsPanel {...panelProps} onBack={onClose} />
        </LemonModal>
    )
}
