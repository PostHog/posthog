import { LemonModal } from '@posthog/lemon-ui'

import { AccessControlLogicProps } from './accessControlLogic'
import { AccessControlObject } from './AccessControlObject'

export interface AccessControlObjectModalProps extends AccessControlLogicProps {
    isOpen: boolean
    onClose: () => void
}

/** Object-level access control (default access, member and role overrides) in a modal,
 * for resources that don't have a full-page scene with the side panel (e.g. warehouse tables). */
export function AccessControlObjectModal({ isOpen, onClose, ...props }: AccessControlObjectModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} width="40rem" simple={false}>
            <AccessControlObject {...props} />
        </LemonModal>
    )
}
