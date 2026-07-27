import { TaxonomicFilterGroupType } from '../types'
import { eventSelectionWasStale, resolveInitialMenuState, resolveSelectedOpenState } from './TaxonomicFilterMenu'
import { MenuFilterEntry, MenuFilterState } from './types'

const entryFor = (type: TaxonomicFilterGroupType): MenuFilterEntry =>
    ({ item: { id: 'a', name: 'a' }, group: { type }, name: 'a' }) as unknown as MenuFilterEntry

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

describe('resolveSelectedOpenState', () => {
    const hogqlEntry = entryFor(TaxonomicFilterGroupType.HogQLExpression)
    const dwhEntry = entryFor(TaxonomicFilterGroupType.DataWarehouse)
    const eventEntry = entryFor(TaxonomicFilterGroupType.Events)

    it.each<[string, MenuFilterEntry | null, MenuFilterState]>([
        ['no selection -> menu', null, { kind: 'menu' }],
        ['hogql selection -> hogql editor', hogqlEntry, { kind: 'hogql-edit' }],
        [
            'data warehouse selection -> dwh config (origin menu)',
            dwhEntry,
            { kind: 'dwh-config', table: dwhEntry.item, group: dwhEntry.group, origin: 'menu' },
        ],
        ['other selection -> combobox all', eventEntry, { kind: 'combobox', drillTo: 'all' }],
    ])('%s', (_label, selected, expected) => {
        expect(resolveSelectedOpenState(selected)).toEqual(expected)
    })
})

describe('resolveInitialMenuState', () => {
    const hogqlEntry = entryFor(TaxonomicFilterGroupType.HogQLExpression)

    it.each<[string, boolean, 'menu' | 'combobox' | undefined, MenuFilterEntry | null, MenuFilterState]>([
        ['closed when not defaultOpen', false, undefined, null, { kind: 'closed' }],
        ['not defaultOpen ignores defaultOpenState and selection', false, 'combobox', hogqlEntry, { kind: 'closed' }],
        ['defaultOpenState combobox -> combobox all', true, 'combobox', null, { kind: 'combobox', drillTo: 'all' }],
        ['defaultOpenState menu -> menu', true, 'menu', null, { kind: 'menu' }],
        ['no defaultOpenState falls back to selection (none -> menu)', true, undefined, null, { kind: 'menu' }],
        ['no defaultOpenState falls back to selection (hogql)', true, undefined, hogqlEntry, { kind: 'hogql-edit' }],
    ])('%s', (_label, defaultOpen, defaultOpenState, selected, expected) => {
        expect(resolveInitialMenuState(defaultOpen, defaultOpenState, selected)).toEqual(expected)
    })
})
