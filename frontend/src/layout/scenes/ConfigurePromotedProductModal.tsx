import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import {
    PRODUCT_KEY_LABELS,
    PromotedProductTarget,
    promotedProductLogic,
} from '~/layout/panel-layout/ai-first/promotedProductLogic'

export interface ConfigurePromotedProductModalProps {
    isOpen: boolean
    onClose: () => void
}

const PRODUCT_OPTIONS = Object.entries(PRODUCT_KEY_LABELS).map(([value, label]) => ({ value, label }))

export function ConfigurePromotedProductModal({ isOpen, onClose }: ConfigurePromotedProductModalProps): JSX.Element {
    const { pendingKind, pendingProduct, pendingUrl } = useValues(promotedProductLogic)
    const { setPendingKind, setPendingProduct, setPendingUrl, setOverride, clearOverride } =
        useActions(promotedProductLogic)

    const canSave =
        (pendingKind === 'product' && !!pendingProduct) || (pendingKind === 'url' && pendingUrl.trim().length > 0)

    const handleSave = (): void => {
        const target: PromotedProductTarget =
            pendingKind === 'product'
                ? { kind: 'product', value: pendingProduct }
                : { kind: 'url', value: pendingUrl.trim() }
        setOverride(target)
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
            description="Choose a product or link to show at the top of the navbar."
            width="40rem"
            footer={
                <div className="flex w-full justify-between gap-2">
                    <LemonButton type="tertiary" onClick={handleReset}>
                        Reset to onboarding default
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleSave}
                            disabledReason={canSave ? undefined : 'Pick a target'}
                            data-attr="configure-promoted-product-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <section className="flex flex-col gap-3">
                <LemonSegmentedButton
                    value={pendingKind}
                    onChange={(newValue) => setPendingKind(newValue)}
                    options={[
                        { value: 'product', label: 'Product' },
                        { value: 'url', label: 'URL' },
                    ]}
                />

                {pendingKind === 'product' && (
                    <LemonSelect<string>
                        fullWidth
                        value={pendingProduct}
                        onChange={(value) => setPendingProduct(value)}
                        options={PRODUCT_OPTIONS}
                        data-attr="configure-promoted-product-select"
                    />
                )}

                {pendingKind === 'url' && (
                    <LemonInput
                        value={pendingUrl}
                        onChange={setPendingUrl}
                        placeholder="/my-dashboard or https://example.com"
                        data-attr="configure-promoted-product-url"
                    />
                )}
            </section>
        </LemonModal>
    )
}
