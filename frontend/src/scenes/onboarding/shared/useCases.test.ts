import { getTreeItemsProducts } from '~/products'

import {
    DOCS_URL_BY_PRODUCT_PATH,
    ONBOARDING_PRODUCTS,
    ONBOARDING_USE_CASES,
    SUPPORTED_ONBOARDING_PRODUCTS,
} from './useCases'

describe('onboarding use cases', () => {
    it('covers every supported product with a visible use case', () => {
        const coveredProducts = new Set(
            ONBOARDING_USE_CASES.flatMap((useCase) => [
                ...useCase.products.map((product) => ONBOARDING_PRODUCTS[product].productKey),
                ...(useCase.additionalProducts ?? []),
            ])
        )

        expect(coveredProducts).toEqual(new Set(SUPPORTED_ONBOARDING_PRODUCTS))
    })

    it('resolves every onboarding product through the product registry', () => {
        const productPaths = new Set(getTreeItemsProducts().map((item) => item.path))

        for (const product of Object.values(ONBOARDING_PRODUCTS)) {
            expect(productPaths).toContain(product.productPath)
            expect(DOCS_URL_BY_PRODUCT_PATH[product.productPath]).toEqual(expect.any(String))
        }
    })

    it('keeps preview-gated products out of onboarding completion', () => {
        // Marking a product "onboarding completed" as a side effect of an unrelated use case
        // must not happen for a product the user cannot open afterwards. Metrics is behind an
        // early access feature with no self-serve enrollment (the gate renders as a dead toggle),
        // so completing onboarding for it tells the user onboarding is complete for a product
        // they cannot open, and `has_completed_onboarding_for` records a false adoption signal.
        const intentOnlyProducts = ONBOARDING_USE_CASES.flatMap((useCase) => useCase.additionalProducts ?? [])

        expect(intentOnlyProducts).not.toContain('metrics')
    })
})
