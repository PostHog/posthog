import { EntityTypes } from '~/types'

import { LocalFilter } from '../entityFilterLogic'

export function makeFilter(overrides: Partial<LocalFilter> = {}): LocalFilter {
    return {
        id: '$autocapture',
        name: '$autocapture',
        type: EntityTypes.EVENTS,
        order: 0,
        uuid: 'test-uuid',
        properties: [],
        ...overrides,
    }
}
