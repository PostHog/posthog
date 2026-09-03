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
})
