import { initKeaTests } from '~/test/init'
import {
    CyclotronJobFiltersType,
    HogFunctionTemplateWithSubTemplateType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { hogFunctionTemplateListLogic } from './hogFunctionTemplateListLogic'

describe('hogFunctionTemplateListLogic - configuration structure', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('should wrap filters in configuration object, not spread at top level', () => {
        const alertId = 'test-alert-id-123'
        const getConfigurationOverrides = (): CyclotronJobFiltersType => ({
            properties: [
                {
                    key: 'alert_id',
                    value: alertId,
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
            events: [{ id: '$insight_alert_firing', type: 'events' as const }],
        })

        const logic = hogFunctionTemplateListLogic.build({
            type: 'destination',
            getConfigurationOverrides,
        })
        logic.mount()

        const template: HogFunctionTemplateWithSubTemplateType = {
            id: 'template-slack',
            name: 'Slack',
            type: 'destination',
            status: 'stable',
            free: true,
            code: 'return event',
            code_language: 'hog',
            sub_template_id: 'insight-alert-firing',
        }

        const url = logic.values.urlForTemplate(template)
        expect(url).toBeTruthy()

        // Parse URL to verify structure
        const urlObj = new URL(url!, window.location.origin)
        const hashParams = new URLSearchParams(urlObj.hash.substring(1))
        const configuration = JSON.parse(decodeURIComponent(hashParams.get('configuration') || '{}'))

        // filters must be wrapped, not at top level
        expect(configuration).toHaveProperty('filters')
        expect(configuration.filters).toHaveProperty('properties')
        expect(configuration).not.toHaveProperty('properties') // Should not be at top level
    })
})
