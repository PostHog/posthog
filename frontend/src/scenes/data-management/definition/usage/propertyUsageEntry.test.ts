import { PropertyDefinitionType } from '~/types'

import { PropertyUsageSource, propertyUsageEntry } from './propertyUsageEntry'

describe('propertyUsageEntry', () => {
    test.each<[string, PropertyUsageSource, ReturnType<typeof propertyUsageEntry>]>([
        [
            'event property',
            { name: '$browser', type: PropertyDefinitionType.Event },
            { type: 'event', name: '$browser' },
        ],
        ['person property', { name: 'email', type: PropertyDefinitionType.Person }, { type: 'person', name: 'email' }],
        [
            'session property',
            { name: '$session_duration', type: PropertyDefinitionType.Session },
            { type: 'session', name: '$session_duration' },
        ],
        [
            'group property keeps its group type index, including 0',
            { name: 'plan', type: PropertyDefinitionType.Group, group_type_index: 0 },
            { type: 'group', name: 'plan', group_type_index: 0 },
        ],
        [
            'group property without a group type index',
            { name: 'plan', type: PropertyDefinitionType.Group, group_type_index: null },
            null,
        ],
        [
            'non-group property drops a stray group type index',
            { name: 'email', type: PropertyDefinitionType.Person, group_type_index: 1 },
            { type: 'person', name: 'email' },
        ],
        ['unsupported type', { name: 'distinct_id', type: PropertyDefinitionType.PersonMetadata }, null],
        ['unknown type', { name: '$browser' }, null],
        ['virtual property', { name: '$virt_channel_type', type: PropertyDefinitionType.Event, virtual: true }, null],
    ])('%s', (_, definition, expected) => {
        expect(propertyUsageEntry(definition)).toEqual(expected)
    })
})
