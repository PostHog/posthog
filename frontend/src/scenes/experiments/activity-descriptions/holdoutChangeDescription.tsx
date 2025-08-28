import { match } from 'ts-pattern'

import { ActivityChange } from 'lib/components/ActivityLog/humanizeActivity'

import { ExperimentHoldoutType } from '~/types'

type AllowedHoldoutFields = Pick<ExperimentHoldoutType, 'name' | 'description' | 'filters'>

export const getHoldoutChangeDescription = (holdoutChange: ActivityChange): string | JSX.Element | null => {
    /**
     * a little type assertion to force field into the allowed holdout fields
     */
    return match(holdoutChange as ActivityChange & { field: keyof AllowedHoldoutFields })
        .with({ field: 'name' }, () => {
            return 'updated experiment holdout name:'
        })
        .with({ field: 'description' }, () => {
            return 'updated experiment holdout description:'
        })
        .with({ field: 'filters' }, () => {
            return 'updated experiment holdout filters:'
        })
        .otherwise(() => null)
}
