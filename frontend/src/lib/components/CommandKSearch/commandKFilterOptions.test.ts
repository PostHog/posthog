import { viewAllItem } from './commandKFilterOptions'
import { QueryChip } from './commandKQuery'

const chip = (value: string, label: string, overrides: Partial<QueryChip> = {}): QueryChip => ({
    key: 'is',
    value,
    label,
    negated: false,
    ...overrides,
})

describe('viewAllItem', () => {
    test.each([
        ['a manifest list page', [chip('feature_flag', 'Feature flag')], 'View all feature flags', '/feature_flags'],
        ['a type with a fallback page', [chip('dashboard', 'Dashboard')], 'View all dashboards', '/dashboard'],
        [
            'other filters alongside',
            [chip('feature_flag', 'Feature flag'), chip('me', 'Me', { key: 'createdBy' })],
            'View all feature flags',
            '/feature_flags',
        ],
    ])('names the list page for %s', (_, chips, name, href) => {
        expect(viewAllItem(chips)).toMatchObject({ name, href })
    })

    test.each([
        ['no is chip', [chip('me', 'Me', { key: 'createdBy' })]],
        ['a negated is chip', [chip('feature_flag', 'Feature flag', { negated: true })]],
        ['a type with no list page', [chip('folder', 'Folder')]],
    ])('returns nothing for %s', (_, chips) => {
        expect(viewAllItem(chips)).toBeNull()
    })
})
