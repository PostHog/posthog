import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { ConfigureHomeModalContent } from './ConfigureHomeModalContent'

export interface ConfigureHomeModalProps {
    isOpen: boolean
    onClose: () => void
}

export function ConfigureHomeModal({ isOpen, onClose }: ConfigureHomeModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Configure homepage"
            description="Choose your personal homepage for this project."
            width="48rem"
        >
            {isOpen && <ConfigureHomeModalContent />}
        </LemonModal>
    )
}
