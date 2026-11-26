import { ActionType, FilterLogicalOperator, RecordingUniversalFilters } from '~/types'

/** Replay filters that list the recordings in which the action happened. */
export function actionRecordingsFilters(action: ActionType): Partial<RecordingUniversalFilters> {
    return {
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            id: action.id,
                            type: 'actions',
                            order: 0,
                            name: action.name,
                        },
                    ],
                },
            ],
        },
    }
}
