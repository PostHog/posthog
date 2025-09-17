import { match } from 'ts-pattern'

import { ActivityChange } from 'lib/components/ActivityLog/humanizeActivity'

import { ExperimentHoldoutType } from '~/types'

type AllowedHoldoutFields = Pick<ExperimentHoldoutType, 'name' | 'description' | 'filters'>

export const getHoldoutChangeDescription = (holdoutChange: ActivityChange): string =>
    match(holdoutChange.field as keyof AllowedHoldoutFields)
        .with('name', () => {
            return 'updated experiment holdout name:'
        })
        .with('description', () => {
            return 'updated experiment holdout description:'
        })
        .with('filters', () => {
            return 'updated experiment holdout filters:'
        })
        .exhaustive()
