import { ActivityScope } from '~/types'

import { getExperimentChangeDescription } from './experimentChangeDescription'

describe('experiment-change-descriptions', () => {
    it('skips unknown exposure_criteria keys instead of throwing', () => {
        const change = {
            type: ActivityScope.EXPERIMENT,
            action: 'changed' as const,
            field: 'exposure_criteria',
            before: { filterTestAccounts: false },
            after: { filterTestAccounts: true, properties: [{ key: 'email', value: 'test' }] },
        }

        const result = getExperimentChangeDescription(change)

        expect(result).toEqual(['added the test account filter'])
    })
})
