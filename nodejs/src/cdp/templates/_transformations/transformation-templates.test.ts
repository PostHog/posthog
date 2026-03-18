import { HogFunctionTemplate } from '~/cdp/types'

import { HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS, HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED } from '../index'

describe('Transformation templates', () => {
    const allTransformationTemplates: HogFunctionTemplate[] = [
        ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS,
        ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED,
    ]

    it('should have free property set to true for all transformation templates', () => {
        for (const template of allTransformationTemplates) {
            expect(template.free).toBe(true)
        }
    })
})
