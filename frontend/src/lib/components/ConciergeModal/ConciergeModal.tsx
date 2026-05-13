import { LemonModal } from 'lib/lemon-ui/LemonModal'

export interface ConciergeModalProps {
    isOpen: boolean
    onClose: () => void
}

export function ConciergeModal({ isOpen, onClose }: ConciergeModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple width={720}>
            <div className="flex items-center justify-center" style={{ height: 540 }}>
                {/* TODO: Add concierge content/art here */}
            </div>
        </LemonModal>
    )
}
