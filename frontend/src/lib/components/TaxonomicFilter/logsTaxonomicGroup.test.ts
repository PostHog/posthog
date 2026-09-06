import { LOGS_TAXONOMIC_OPTIONS, logsColumnValuesEndpoint } from './logsTaxonomicGroup'

describe('logsTaxonomicGroup', () => {
    it('offers service_name as a column filter, not a log attribute', () => {
        // The picker's only other `service_name` is a log attribute holding namespace/container
        // values the column never equals — a filter built on it silently matches nothing. The
        // column option must exist and must carry the `log` filter type so the matcher and the
        // query builder resolve it to the column.
        const serviceOption = LOGS_TAXONOMIC_OPTIONS.find((o) => o.key === 'service_name')
        expect(serviceOption).toEqual({ key: 'service_name', name: 'service_name', propertyFilterType: 'log' })
    })

    it('suggests service values from the resource service.name, never the log-attribute map', () => {
        // The `service_name` column is populated from the resource `service.name` attribute, so
        // that is the only lookup whose suggestions the column can equal. Pointing this at
        // `attribute_type=log` resurfaces the namespace/container values.
        const endpoint = logsColumnValuesEndpoint(2, { dateRange: { date_from: '-1h' } })('service_name')

        expect(endpoint).toContain('api/projects/2/logs/values')
        expect(endpoint).toContain('attribute_type=resource')
        expect(endpoint).toContain('key=service.name')
        expect(endpoint).not.toContain('attribute_type=log')
    })

    it.each(['message', 'severity_level', 'trace_id', 'span_id'])('leaves %s on its existing value input', (key) => {
        // message is free-text, severity_level has an enum select, trace/span ids are typed by
        // hand. Returning an endpoint for them would replace those inputs with a fetch.
        expect(logsColumnValuesEndpoint(2, {})(key)).toBeUndefined()
    })
})
