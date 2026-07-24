import { useValues } from 'kea'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { QUICKSTART_PRODUCT_LAYOUT } from '../productLayout'
import { quickstartLogic } from '../quickstartLogic'
import { SimplifiedToolRow } from './SimplifiedToolRow'

/** The non-featured tools, one row each. Picking a tool closes the dialog; pinning
 * moves the tool to Your tools and keeps the dialog open. */
export function ExploreToolsModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { additionalProducts } = useValues(quickstartLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={QUICKSTART_PRODUCT_LAYOUT.additional.title}
            description={QUICKSTART_PRODUCT_LAYOUT.additional.description}
            width="40rem"
        >
            {additionalProducts.length > 0 ? (
                <div className="flex flex-col gap-2">
                    {additionalProducts.map((product) => (
                        <SimplifiedToolRow key={product.key} product={product} onAction={onClose} />
                    ))}
                </div>
            ) : (
                <p className="text-secondary mb-0">Every tool is in Your tools already.</p>
            )}
        </LemonModal>
    )
}
