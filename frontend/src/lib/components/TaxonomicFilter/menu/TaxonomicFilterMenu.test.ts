import { TaxonomicFilterGroupType } from '../types'
import { eventSelectionWasStale } from './TaxonomicFilterMenu'

describe('eventSelectionWasStale', () => {
    const staleEvent = { name: 'old', last_seen_at: '2000-01-01T00:00:00Z' } as any
    const freshEvent = { name: 'new', last_seen_at: new Date().toISOString() } as any

    it.each([
        ['stale event definition', TaxonomicFilterGroupType.Events, staleEvent, true],
        ['fresh event definition', TaxonomicFilterGroupType.Events, freshEvent, false],
        ['stale custom-event definition', TaxonomicFilterGroupType.CustomEvents, staleEvent, true],
        ['non-event group', TaxonomicFilterGroupType.EventProperties, staleEvent, undefined],
        ['event row without last_seen_at', TaxonomicFilterGroupType.Events, { name: 'x' }, undefined],
    ])('%s -> %s', (_label, groupType, item, expected) => {
        expect(eventSelectionWasStale(groupType as TaxonomicFilterGroupType, item)).toBe(expected)
    })
})
