import { LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { PartnerBillingLimitProduct } from './partnerBillingForms'

interface PartnerBillingLimitFieldsProps {
    fieldName: string
    products: PartnerBillingLimitProduct[]
    productsLoading: boolean
    placeholders?: Record<string, string>
}

export function PartnerBillingLimitFields({
    fieldName,
    products,
    productsLoading,
    placeholders,
}: PartnerBillingLimitFieldsProps): JSX.Element {
    if (products.length === 0) {
        return productsLoading ? (
            <LemonSkeleton className="h-10 max-w-120" />
        ) : (
            <p className="text-secondary text-sm mb-0">
                The product list didn't load, so limits can't be set right now. Reload the page to try again.
            </p>
        )
    }

    return (
        <div className="flex flex-wrap items-end gap-4">
            {products.map((product) => (
                <LemonField key={product.key} name={[fieldName, product.key]} label={product.name} className="w-44">
                    {({ value, onChange, error }) => (
                        <LemonInput
                            type="number"
                            min={0}
                            step={1}
                            prefix={<b>$</b>}
                            placeholder={placeholders?.[product.key] ?? 'No limit'}
                            status={error ? 'danger' : 'default'}
                            // LemonInput reports a cleared number field as NaN and shows NaN as empty,
                            // while the API takes null as no limit.
                            value={value ?? NaN}
                            onChange={(limit) => onChange(limit === undefined || Number.isNaN(limit) ? null : limit)}
                            data-attr={`partner-billing-limit-${product.key}`}
                        />
                    )}
                </LemonField>
            ))}
        </div>
    )
}
