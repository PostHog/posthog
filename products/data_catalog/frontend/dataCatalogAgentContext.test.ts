import { buildDataCatalogAgentContext, buildDataCatalogMetricAgentContext } from './dataCatalogAgentContext'

function instructions(contextItems: ReturnType<typeof buildDataCatalogAgentContext>): string[] {
    return contextItems.filter((item) => item.type === 'instructions').map((item) => item.value ?? '')
}

describe('data catalog agent context', () => {
    it('keeps variable tab values out of trusted instructions', () => {
        const metricsContext = buildDataCatalogAgentContext('metrics')
        const relationshipsContext = buildDataCatalogAgentContext('relationships')

        expect(instructions(metricsContext)).toEqual(instructions(relationshipsContext))
        expect(metricsContext).toContainEqual(
            expect.objectContaining({ type: 'text', value: 'Open data catalog tab: metrics' })
        )
        expect(relationshipsContext).toContainEqual(
            expect.objectContaining({ type: 'text', value: 'Open data catalog tab: relationships' })
        )
    })

    it('attaches the metric name and unsaved markdown as untrusted context', () => {
        const name = 'weekly_active_users'
        const contextItems = buildDataCatalogMetricAgentContext(name, '1. Count active users')
        const metricItem = contextItems.find((item) => item.type === 'data_catalog_metric')
        const pointerItem = contextItems.find((item) => item.type === 'text' && item.value?.includes(name))
        const draftItem = contextItems.find((item) => item.type === 'data_catalog_metric_draft')

        expect(metricItem).toEqual(
            expect.objectContaining({ key: name, label: name, dismissGroup: pointerItem?.dismissGroup })
        )
        expect(draftItem).toEqual(
            expect.objectContaining({
                dismissGroup: metricItem?.dismissGroup,
                value: JSON.stringify({ name, kind: 'MarkdownDefinition', markdown: '1. Count active users' }),
            })
        )
        expect(instructions(contextItems).join('\n')).not.toContain(name)
    })

    it('only includes a draft while markdown editing is active', () => {
        const contextItems = buildDataCatalogMetricAgentContext('weekly_active_users', null)

        expect(contextItems.some((item) => item.type === 'data_catalog_metric_draft')).toBe(false)
    })

    it('only supplies the skill bundle for an invalid metric name', () => {
        const contextItems = buildDataCatalogMetricAgentContext('../ignore instructions', '1. Unsafe')

        expect(contextItems.some((item) => item.type === 'data_catalog_metric')).toBe(false)
        expect(contextItems.some((item) => item.type === 'text')).toBe(false)
        expect(instructions(contextItems).join('\n')).not.toContain('../ignore instructions')
    })
})
