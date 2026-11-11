import posthog from 'posthog-js'

import {
    BI_EDITOR_EVENTS,
    captureBIEditorQueryRun,
    captureBIEditorQuerySaved,
    captureBIWorksheetAction,
} from './biEditorAnalytics'
import { BIEditorView, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('BI usage tracking', () => {
    it('records capabilities while excluding worksheet contents from every event', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const field = {
            id: 'private-field',
            name: 'properties.private-field',
            expression: 'properties.private-field',
            type: 'float' as const,
            source: { table: 'private-source' },
        }
        const config = {
            ...DEFAULT_BI_CONFIG,
            source: field.source,
            rows: [field],
            values: [
                {
                    field,
                    aggregation: 'custom' as const,
                    customExpression: 'sum(private-formula)',
                    label: 'private-label',
                    tableCalculation: { type: 'running_total' as const },
                    formatting: { prefix: 'private-prefix' },
                },
            ],
            filters: [{ field, operator: 'equals' as const, value: 'private-value' }],
            topN: { fieldId: field.id, count: 5, measureIndex: 0, includeOther: true },
            compareFilter: { compare: true },
        }
        try {
            const state = { editorView: BIEditorView.BI, config }
            captureBIEditorQueryRun(state)
            captureBIEditorQuerySaved(state, 'insight', 'create')
            captureBIWorksheetAction('drilldown_opened', config)
            expect(capture.mock.calls.map(([event]) => event)).toEqual([
                BI_EDITOR_EVENTS.QUERY_RUN,
                BI_EDITOR_EVENTS.QUERY_SAVED,
                BI_EDITOR_EVENTS.WORKSHEET_ACTION,
            ])
            for (const [, properties] of capture.mock.calls) {
                expect(properties).toMatchObject({
                    table_calculation_types: ['running_total'],
                    top_n_enabled: true,
                    comparison_enabled: true,
                    formatted_measure_count: 1,
                    property_field_count: 3,
                })
                expect(JSON.stringify(properties)).not.toContain('private-')
            }
        } finally {
            capture.mockRestore()
        }
    })
})
