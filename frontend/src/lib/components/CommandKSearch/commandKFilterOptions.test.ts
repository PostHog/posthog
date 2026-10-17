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

const createdByMe = chip('me', 'Me', { key: 'createdBy' })
const notInGrowthTeam = chip('Growth team', 'Growth team', { key: 'in', negated: true })

describe('viewAllFor', () => {
    test.each([
        [
            'a manifest list page',
            [chip('feature_flag', 'Feature flag')],
            '',
            'View all feature flags',
            '/feature_flags',
        ],
        ['a type with a fallback page', [chip('dashboard', 'Dashboard')], '', 'View all dashboards', '/dashboard'],
        [
            'other filters alongside',
            [chip('feature_flag', 'Feature flag'), createdByMe],
            '',
            'View all feature flags',
            '/feature_flags',
        ],
        [
            'a list that searches the text but not the filters',
            [chip('feature_flag', 'Feature flag'), createdByMe],
            'checkout v2',
            'View all feature flags',
            '/feature_flags?search=checkout%20v2',
        ],
        [
            'a list that searches quoted text without its quotes',
            [chip('feature_flag', 'Feature flag')],
            '"checkout v2" beta',
            'View all feature flags',
            '/feature_flags?search=checkout%20v2%20beta',
        ],
        [
            'a list that searches without the excluded words',
            [chip('feature_flag', 'Feature flag')],
            'beta -legacy -"old flow" !draft - ""',
            'View all feature flags',
            '/feature_flags?search=beta',
        ],
        [
            'a list that searches the name filter before the text',
            [chip('feature_flag', 'Feature flag'), chip('checkout', 'checkout', { key: 'name' })],
            'beta',
            'View all feature flags',
            '/feature_flags?search=checkout%20beta',
        ],
        [
            'a list that searches without an excluded name',
            [chip('feature_flag', 'Feature flag'), chip('checkout', 'checkout', { key: 'name', negated: true })],
            '',
            'View all feature flags',
            '/feature_flags',
        ],
        [
            'a fallback page that searches the text',
            [chip('dashboard', 'Dashboard')],
            'revenue',
            'View all dashboards',
            '/dashboard?search=revenue',
        ],
        [
            'a list that reads the whole query',
            [chip('workflows', 'Workflow'), createdByMe, notInGrowthTeam],
            'welcome',
            'View all workflows',
            '/workflows?q=createdBy%3Ame%20-in%3A%22Growth%20team%22%20welcome',
        ],
        [
            'a list that reads no query',
            [chip('action', 'Action'), createdByMe],
            'signup',
            'View all actions',
            '/data-management/actions',
        ],
    ])('names the list page for %s', (_, chips, freeText, name, href) => {
        expect(viewAllFor(resolved(chips, freeText))?.item).toMatchObject({ name, href })
    })

    test.each([
        ['leads with only filters', '', 'lead'],
        ['trails once there is search text', 'beta', 'trail'],
    ])('%s', (_, freeText, placement) => {
        expect(viewAllFor(resolved([chip('feature_flag', 'Feature flag')], freeText))?.placement).toBe(placement)
    })

    test.each([
        ['no is chip', [createdByMe]],
        ['a negated is chip', [chip('feature_flag', 'Feature flag', { negated: true })]],
        ['a type with no list page', [chip('folder', 'Folder')]],
    ])('returns nothing for %s', (_, chips) => {
        expect(viewAllFor(resolved(chips))).toBeNull()
    })
})
