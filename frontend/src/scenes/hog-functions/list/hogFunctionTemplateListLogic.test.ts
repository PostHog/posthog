import { initKeaTests } from '~/test/init'
import {
    CyclotronJobFiltersType,
    HogFunctionTemplateType,
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
        const filters: CyclotronJobFiltersType = {
            properties: [
                {
                    key: 'alert_id',
                    value: alertId,
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
            events: [{ id: '$insight_alert_firing', type: 'events' as const }],
        }
        const getConfigurationOverrides = (): { filters: CyclotronJobFiltersType } => ({ filters })

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

describe('hogFunctionTemplateListLogic - deliveryType filter', () => {
    const makeTemplate = (id: string, name: string): HogFunctionTemplateType => ({
        id,
        name,
        type: 'destination',
        status: 'stable',
        free: true,
        code: '',
        code_language: 'hog',
    })

    const batchTemplate = makeTemplate('batch-export-S3', 'S3 batch export')
    const realtimeTemplate = makeTemplate('template-slack', 'Slack realtime')

    const buildLogic = (): ReturnType<typeof hogFunctionTemplateListLogic.build> => {
        const logic = hogFunctionTemplateListLogic.build({
            type: 'destination',
            manualTemplates: [batchTemplate, realtimeTemplate],
        })
        logic.mount()
        return logic
    }

    beforeEach(() => {
        initKeaTests()
    })

    it('shows both frequencies when no deliveryType filter is set', () => {
        const logic = buildLogic()
        expect(logic.values.filteredTemplates.map((t) => t.id)).toEqual(
            expect.arrayContaining(['batch-export-S3', 'template-slack'])
        )
    })

    it('filters to batch in the non-search branch', () => {
        const logic = buildLogic()
        logic.actions.setFilters({ deliveryType: 'batch' })
        expect(logic.values.filteredTemplates.map((t) => t.id)).toEqual(['batch-export-S3'])
    })

    it('filters to realtime in the non-search branch', () => {
        const logic = buildLogic()
        logic.actions.setFilters({ deliveryType: 'realtime' })
        expect(logic.values.filteredTemplates.map((t) => t.id)).toEqual(['template-slack'])
    })

    it('applies the deliveryType filter in the search branch too', () => {
        const logic = buildLogic()
        // Only the batch template's name contains "export", so the search matches just that one.
        logic.actions.setFilters({ search: 'export', deliveryType: 'batch' })
        expect(logic.values.filteredTemplates.map((t) => t.id)).toEqual(['batch-export-S3'])

        // Same search still matches the batch template, but the realtime filter must drop it —
        // an empty result proves the deliveryType filter is applied inside the search branch.
        logic.actions.setFilters({ search: 'export', deliveryType: 'realtime' })
        expect(logic.values.filteredTemplates.map((t) => t.id)).toEqual([])
    })
})
