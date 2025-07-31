import { HogFunctionType } from '~/cdp/types'
import { isLegacyPluginHogFunction, isNativeHogFunction, isSegmentPluginHogFunction } from '~/cdp/utils'

import { HOG_FUNCTION_TEMPLATES } from '..'

describe('Hog Function Templates Code Language', () => {
    it.each(HOG_FUNCTION_TEMPLATES)('should have correct code_language for template $id', (template) => {
        if (
            isNativeHogFunction({ template_id: template.id } as HogFunctionType) ||
            isSegmentPluginHogFunction({ template_id: template.id } as HogFunctionType) ||
            isLegacyPluginHogFunction({ template_id: template.id } as HogFunctionType) ||
            template.id.startsWith('coming-soon-')
        ) {
            expect(template.code_language).toBe('javascript')
        } else {
            expect(template.code_language).toBe('hog')
        }
    })

    it.each(HOG_FUNCTION_TEMPLATES)('should have hog property set for template $id', (template) => {
        expect(template.code).toBeDefined()
        expect(typeof template.code).toBe('string')
    })
})
