import {
    clampToWidgetDateFrom,
    extractSavedFilterValues,
    LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
} from './llmAnalyticsTracesWidgetConfigValidation'

describe('llmAnalyticsTracesWidgetConfigValidation', () => {
    it('passes through an allowed widget date range', () => {
        expect(clampToWidgetDateFrom('-30d')).toBe('-30d')
    })

    it.each([['-180d'], ['all'], [null], [undefined], ['']])(
        'clamps unsupported saved-filter date range %s to the default',
        (dateFrom) => {
            expect(clampToWidgetDateFrom(dateFrom as string | null | undefined)).toBe(
                LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM
            )
        }
    )

    it('extracts the scalar fields a widget config can store from a saved TracesQuery source', () => {
        expect(
            extractSavedFilterValues({
                dateRange: { date_from: '-14d' },
                filterTestAccounts: true,
                filterSupportTraces: true,
                // Property filters are intentionally not carried into the widget config.
                properties: [{ key: '$ai_model', value: 'gpt-4' }],
            })
        ).toEqual({ dateFrom: '-14d', filterTestAccounts: true, filterSupportTraces: true })
    })

    it('ignores non-boolean toggles and clamps the date when the saved filter is sparse', () => {
        expect(extractSavedFilterValues({ dateRange: { date_from: '-180d' }, filterTestAccounts: 'yes' })).toEqual({
            dateFrom: LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
            filterTestAccounts: null,
            filterSupportTraces: null,
        })
    })

    it('falls back to the default date range when the source is missing', () => {
        expect(extractSavedFilterValues(null)).toEqual({
            dateFrom: LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
            filterTestAccounts: null,
            filterSupportTraces: null,
        })
    })
})
