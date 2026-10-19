import {
    buildSourceAlertFilterGroups,
    buildSourceAlertNameSuffix,
    buildSourceAlertPropertyFilters,
} from './sourceAlertFilters'
import { SOURCE_ALERT_SUB_TEMPLATE_IDS } from './sourceAlertWizardConfig'

describe('sourceAlertFilters', () => {
    const sourceFilter = { key: 'source_id', type: 'event', value: 'abc-123', operator: 'exact' }

    it.each([
        ['no source id', undefined, []],
        ['empty source id', '', []],
        ['a source id', 'abc-123', [sourceFilter]],
    ])('builds property filters for %s', (_name, sourceId, expected) => {
        expect(buildSourceAlertPropertyFilters(sourceId)).toEqual(expected)
    })

    it('builds one bare event filter per alert type at project level', () => {
        const groups = buildSourceAlertFilterGroups()
        expect(groups).toHaveLength(SOURCE_ALERT_SUB_TEMPLATE_IDS.length)
        groups.forEach((group) => {
            expect(group.source).toBe('internal-events')
            expect(group.events).toHaveLength(1)
            expect(group.properties).toBeUndefined()
        })
    })

    it('adds the source filter to every event filter for one source', () => {
        const groups = buildSourceAlertFilterGroups('abc-123')
        expect(groups).toHaveLength(SOURCE_ALERT_SUB_TEMPLATE_IDS.length)
        groups.forEach((group) => {
            expect(group.properties).toEqual([sourceFilter])
        })
    })

    it.each([
        ['both set', 'abc-123', 'Stripe', 'for Stripe'],
        ['no name', 'abc-123', undefined, undefined],
        ['no source id', undefined, 'Stripe', undefined],
    ])('builds the name suffix with %s', (_name, sourceId, sourceName, expected) => {
        expect(buildSourceAlertNameSuffix(sourceId, sourceName)).toBe(expected)
    })
})
