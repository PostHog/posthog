import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import {
    labelForPromotedProductKey,
    PROMOTED_PRODUCT_KEYS,
    promotedProductLogic,
} from '~/layout/panel-layout/ai-first/promotedProductLogic'

export interface ConfigurePromotedProductModalProps {
    isOpen: boolean
    onClose: () => void
}

const PRODUCT_OPTIONS = PROMOTED_PRODUCT_KEYS.map((value) => ({ value, label: labelForPromotedProductKey(value) }))

export function ConfigurePromotedProductModal({ isOpen, onClose }: ConfigurePromotedProductModalProps): JSX.Element {
    const { pendingProduct, defaultProductKey, override } = useValues(promotedProductLogic)
    const { setPendingProduct, setOverride, clearOverride } = useActions(promotedProductLogic)

    const handleSave = (): void => {
        setOverride(pendingProduct)
        onClose()
    }

    const handleReset = (): void => {
        clearOverride()
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Configure promoted product"
            description="Choose the product to show at the top of the navbar."
            width="30rem"
            footer={
                <div className="flex w-full justify-between gap-2">
                    <LemonButton
                        type="tertiary"
                        onClick={handleReset}
                        disabledReason={override ? undefined : 'No override to reset'}
                    >
                        Reset to default ({labelForPromotedProductKey(defaultProductKey)})
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" onClick={handleSave} data-attr="configure-promoted-product-save">
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonSelect<string>
                fullWidth
                value={pendingProduct}
                onChange={(value) => setPendingProduct(value)}
                options={PRODUCT_OPTIONS}
                data-attr="configure-promoted-product-select"
            />
        </LemonModal>
    )
}
