import { findElement } from 'posthog-js/dist/element-inference'

import { getStepElement, TourStep } from './productToursLogic'

jest.mock('posthog-js/dist/element-inference', () => ({
    findElement: jest.fn(),
}))

describe('productToursLogic', () => {
    const stepWithInference = {
        id: 'step-1',
        type: 'tooltip',
        elementTargeting: 'auto',
        inferenceData: { autoData: '{}', text: null },
    } as unknown as TourStep

    it('getStepElement returns null instead of throwing when findElement throws on malformed inference data', () => {
        // findElement (posthog-js) normalizes captured element text/tag with toLowerCase and can throw
        // "Cannot read properties of undefined (reading 'toLowerCase')" on arbitrary customer pages
        ;(findElement as jest.Mock).mockImplementation(() => {
            throw new TypeError("Cannot read properties of undefined (reading 'toLowerCase')")
        })
        expect(() => getStepElement(stepWithInference)).not.toThrow()
        expect(getStepElement(stepWithInference)).toBeNull()
    })

    it('getStepElement returns the element that findElement resolves', () => {
        const element = document.createElement('button')
        ;(findElement as jest.Mock).mockReturnValue(element)
        expect(getStepElement(stepWithInference)).toBe(element)
    })
})
