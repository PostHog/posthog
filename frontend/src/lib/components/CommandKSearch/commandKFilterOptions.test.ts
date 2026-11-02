import { viewAllFor } from './commandKFilterOptions'
import { QueryChip, ResolvedQuery } from './commandKQuery'

const chip = (value: string, label: string, overrides: Partial<QueryChip> = {}): QueryChip => ({
    key: 'is',
    value,
    label,
    negated: false,
    ...overrides,
})

const resolved = (filters: QueryChip[], freeText = ''): ResolvedQuery => ({ filters, freeText, backendSearch: '' })

describe('viewAllFor', () => {
    test.each([
        ['a manifest list page', [chip('feature_flag', 'Feature flag')], 'View all feature flags', '/feature-flags'],
        ['a type with a fallback page', [chip('dashboard', 'Dashboard')], 'View all dashboards', '/dashboard'],
        [
            'other filters alongside',
            [chip('feature_flag', 'Feature flag'), chip('me', 'Me', { key: 'createdBy' })],
            'View all feature flags',
            '/feature-flags',
        ],
    ])('names the list page for %s', (_, chips, name, href) => {
        expect(viewAllFor(resolved(chips))?.item).toMatchObject({ name, href })
    })

    test.each([
        ['leads with only filters', '', 'lead'],
        ['trails once there is search text', 'beta', 'trail'],
    ])('%s', (_, freeText, placement) => {
        expect(viewAllFor(resolved([chip('feature_flag', 'Feature flag')], freeText))?.placement).toBe(placement)
    })

    test.each([
        ['no is chip', [chip('me', 'Me', { key: 'createdBy' })]],
        ['a negated is chip', [chip('feature_flag', 'Feature flag', { negated: true })]],
        ['a type with no list page', [chip('folder', 'Folder')]],
    ])('returns nothing for %s', (_, chips) => {
        expect(viewAllFor(resolved(chips))).toBeNull()
    })
})
