import { getTreeItemsProducts } from '~/products'

import { DOCS_URL_BY_PRODUCT_PATH, ONBOARDING_TOOLS, ONBOARDING_USE_CASES, SUPPORTED_TOOL_PRODUCTS } from './useCases'

describe('onboarding use cases', () => {
    it('covers every supported tool with a visible use case', () => {
        const coveredProducts = new Set(
            ONBOARDING_USE_CASES.flatMap((useCase) => [
                ...useCase.tools.map((tool) => ONBOARDING_TOOLS[tool].productKey),
                ...(useCase.additionalTools ?? []),
            ])
        )

        expect(coveredProducts).toEqual(new Set(SUPPORTED_TOOL_PRODUCTS))
    })

    it('resolves every onboarding tool through the product registry', () => {
        const productPaths = new Set(getTreeItemsProducts().map((item) => item.path))

        for (const tool of Object.values(ONBOARDING_TOOLS)) {
            expect(productPaths).toContain(tool.productPath)
            expect(DOCS_URL_BY_PRODUCT_PATH[tool.productPath]).toEqual(expect.any(String))
        }
    })

    it('keeps preview-gated products out of onboarding completion', () => {
        // Marking a product "onboarding completed" as a side effect of an unrelated use case
        // must not happen for a product the user cannot open afterwards. Metrics is behind an
        // early access feature with no self-serve enrollment (the gate renders as a dead toggle),
        // so completing onboarding for it tells the user onboarding is complete for a product
        // they cannot open, and `has_completed_onboarding_for` records a false adoption signal.
        const intentOnlyProducts = ONBOARDING_USE_CASES.flatMap((useCase) => useCase.additionalTools ?? [])

        expect(intentOnlyProducts).not.toContain('metrics')
    })
})
