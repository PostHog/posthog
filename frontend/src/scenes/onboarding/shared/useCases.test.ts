import { ONBOARDING_TOOLS, ONBOARDING_USE_CASES, SUPPORTED_TOOL_PRODUCTS } from './useCases'

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
})
