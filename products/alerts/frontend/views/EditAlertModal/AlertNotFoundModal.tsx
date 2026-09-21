import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function AlertNotFoundModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal onClose={onClose} isOpen={isOpen} width={900} simple title="">
            <div className="flex min-h-[600px] flex-col items-center justify-center gap-3 p-6 text-center">
                <HedgehogMagnifyingGlass className="h-28 w-28" />
                <h2 className="m-0 text-lg font-semibold">Alert not found</h2>
                <p className="m-0 text-secondary">This alert may have been deleted.</p>
                <LemonButton type="secondary" onClick={onClose}>
                    Back to alerts
                </LemonButton>
            </div>
        </LemonModal>
    )
}
